import yt_dlp
from rich import print
import sounddevice as sd
import soundfile as sf
import os
import shlex
import threading
import keyboard
import numpy as np

# --------------------------
# Settings
# --------------------------
volume = 0.5
loaded = {}  # <name>: [<url>, <audio_data>, <samplerate>]
os.makedirs("downloads", exist_ok=True)

# Playback control storage
playback_sessions = {}  # <name>: {"pause": Event, "stop": Event, "threads": [Thread]}

# --------------------------
# Device selection
# --------------------------
def choose_output_devices():
    print("=== Output Devices ===")
    devs = sd.query_devices()
    for idx, dev in enumerate(devs):
        if dev['max_output_channels'] > 0:
            print(f"[{idx}] {dev['name']} (hostapi={dev['hostapi']})")
    try:
        d1 = int(input("Primary output device ID: ").strip())
        d2 = int(input("Secondary output device ID (loopback/mic): ").strip())
        return d1, d2
    except ValueError:
        print("Invalid device ID.")
        raise SystemExit(1)

primary_device, secondary_device = choose_output_devices()

# --------------------------
# YouTube URL validation
# --------------------------
def is_valid_youtube(url: str) -> bool:
    ydl_opts = {'quiet': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=False)
        return True
    except yt_dlp.utils.DownloadError:
        return False

# --------------------------
# Audio playback
# --------------------------
def play_with_control(data, samplerate, device, pause_event, stop_event):
    blocksize = 1024
    n_channels = data.shape[1] if len(data.shape) > 1 else 1
    try:
        with sd.OutputStream(samplerate=samplerate, channels=n_channels, device=device, blocksize=blocksize) as stream:
            for i in range(0, len(data), blocksize):
                if stop_event.is_set():
                    break
                while pause_event.is_set() and not stop_event.is_set():
                    sd.sleep(50)
                if stop_event.is_set():
                    break
                chunk = data[i:i+blocksize]
                chunk_volume = chunk * volume
                stream.write(chunk_volume)
    except Exception as e:
        print(f"[red]Device {device} error: {e}")

def setup_keyboard_controls(pause_event, stop_event):
    """Attach hotkeys for a playback session."""
    def toggle_pause():
        if pause_event.is_set():
            pause_event.clear()
            print("[yellow]Resuming playback...")
        else:
            pause_event.set()
            print("[yellow]Paused playback. Press Ctrl+X to resume...")

    def stop_playback():
        stop_event.set()
        print("[red]Playback cancelled!")

    keyboard.add_hotkey("ctrl+x", toggle_pause)
    keyboard.add_hotkey("ctrl+z", stop_playback)

def clear_playback_hotkeys():
    try:
        keyboard.clear_all_hotkeys()
    except Exception:
        pass

def play_audio(name):
    if name not in loaded:
        print(f"[red]No such loaded track: '{name}'")
        return

    data, samplerate = loaded[name][1], loaded[name][2]

    # Reset control events
    pause_event = threading.Event()
    stop_event = threading.Event()

    # Setup keyboard hooks for this session
    setup_keyboard_controls(pause_event, stop_event)

    # Start playback threads for both devices
    threads = [
        threading.Thread(target=play_with_control, args=(data, samplerate, primary_device, pause_event, stop_event)),
        threading.Thread(target=play_with_control, args=(data, samplerate, secondary_device, pause_event, stop_event))
    ]
    for t in threads:
        t.daemon = True
        t.start()

    # Store session so it can be stopped or paused externally
    playback_sessions[name] = {
        "pause": pause_event,
        "stop": stop_event,
        "threads": threads
    }

    print(f"[yellow]Playback started for '{name}'. Use Ctrl+X to pause/resume, Ctrl+Z to stop.")

# --------------------------
# Main loop
# --------------------------
try:
    while True:
        try:
            usr_in = input("URL PLAYER v2.0\n> ")
        except EOFError:
            print("[yellow]EOF received — ignoring.")
            continue

        if not usr_in:
            continue

        try:
            cmds = shlex.split(usr_in)
        except ValueError as e:
            print(f"[red]Failed to parse command: {e}")
            continue

        if not cmds:
            continue

        cmd = cmds[0].lower()

        if cmd == "help":
            print("[green]VERSION: [red]2.0")
            print("[blue]COMMANDS:")
            print("[white]- load <url> <name> [--save]   [yellow]Load YouTube URL as <name>, optionally save as WAV")
            print("[white]- unload <name>               [yellow]Unload the given track")
            print("[white]- list                         [yellow]List loaded tracks")
            print("[white]- play <name>                  [yellow]Play track asynchronously (Ctrl+X pause/resume, Ctrl+Z stop)")
            print("[white]- volume <value>               [yellow]Set volume (0.0-1.0)")

        elif cmd == "load":
            if len(cmds) < 3:
                print("[red]Usage: load <url> <name> [--save]")
                continue

            url, name = cmds[1], cmds[2]
            flags = {"save": "--save" in cmds[3:]}

            if not is_valid_youtube(url):
                print(f"[red]Invalid YouTube URL: {url}")
                continue

            download_path = f"downloads/{name}.%(ext)s" if flags["save"] else f"downloads/{name}.temp.%(ext)s"

            download_ydl_opts = {
                'cookies': 'cookies.txt',
                'format': 'bestaudio/best',
                'outtmpl': download_path,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'quiet': True,
            }

            print(f"[green]Downloading '{name}'...")
            try:
                with yt_dlp.YoutubeDL(download_ydl_opts) as ydl:
                    ydl.download([url])
            except Exception as e:
                print(f"[red]yt-dlp error: {e}")
                continue

            audio_file = download_path.replace("%(ext)s", "wav")
            if os.path.exists(audio_file):
                try:
                    data, samplerate = sf.read(audio_file, dtype='float32')
                    loaded[name] = [url, data, samplerate]
                    print(f"[green]Loaded '{name}' successfully!")
                except Exception as e:
                    print(f"[red]Failed to read audio: {e}")
                finally:
                    if not flags["save"]:
                        try: os.remove(audio_file)
                        except Exception: pass
            else:
                print(f"[red]File not found after download: {audio_file}")

        elif cmd == "unload":
            if len(cmds) < 2:
                print("[red]Usage: unload <name>")
                continue
            name = cmds[1]
            if name in loaded:
                # stop playback if playing
                if name in playback_sessions:
                    playback_sessions[name]["stop"].set()
                    for t in playback_sessions[name]["threads"]:
                        t.join()
                    del playback_sessions[name]
                del loaded[name]
                print(f"[yellow]Unloaded '{name}'.")
            else:
                print(f"[red]No such loaded track: '{name}'")

        elif cmd == "list":
            if loaded:
                print("[blue]Loaded tracks:")
                for name in loaded:
                    print(f" - [green]{name}")
            else:
                print("[yellow]No tracks loaded.")

        elif cmd == "play":
            if len(cmds) < 2:
                print("[red]Usage: play <name>")
                continue
            name = cmds[1]
            # stop previous playback of same track
            if name in playback_sessions:
                playback_sessions[name]["stop"].set()
                for t in playback_sessions[name]["threads"]:
                    t.join()
                del playback_sessions[name]
            play_audio(name)

        elif cmd == "volume":
            if len(cmds) < 2:
                print("[red]Usage: volume <value>")
                continue
            try:
                volume = float(cmds[1])
                print(f"[green]Volume set to {volume:.2f}")
            except ValueError:
                print("[red]Volume must be a float between 0.0 and 1.0")

        else:
            print("[red]Unknown command. Type 'help' for commands.")

except KeyboardInterrupt:
    print("\n[yellow]CTRL+C received, exiting.")
    # stop all playbacks
    for name, session in playback_sessions.items():
        session["stop"].set()
        for t in session["threads"]:
            t.join()
    clear_playback_hotkeys()
    raise SystemExit(0)
