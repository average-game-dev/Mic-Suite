import os
import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import keyboard
from keymods import is_numlock_on
import random
import subprocess
import time
import json
from mutagen import File as MutagenFile
from rich import print

# --------------------------
# Settings
# --------------------------
stream_sr = 48000
stream_channels = 2
blocksize = 1024
master_gain = 1.0
gain_step = 0.05

playlist_json = "playlists.json"  # JSON file with playlists
shuffle_mode = False
random_any_mode = False
status_enabled = True
debug_status_enabled = False

def get_track_info(file, default_title="Unknown Track"):
    """
    Reads track title and artist from audio files (wav, mp3, flac, m4a, ogg).
    Returns a tuple: (title, artist)
    
    - default_title: used if the track title is missing
    - artist defaults to "UNKNOWN"
    """
    audio = MutagenFile(file, easy=True)
    title = default_title
    artist = "UNKNOWN"

    if audio is not None:
        # 'title' and 'artist' are standardized in EasyID3/EasyTags
        if "title" in audio and audio["title"]:
            title = audio["title"][0]
        if "artist" in audio and audio["artist"]:
            artist = audio["artist"][0]

    return {"title":title, "artist":artist}

def load_audio_ffmpeg(file):
    """
    Load audio via ffmpeg and return stereo float32 NumPy array.
    
    WAV:
        - resample to target_sr
        - loudness normalize
    Non-WAV:
        - resample only (no loudnorm)
    """

    ext = os.path.splitext(file)[1].lower()

    # Base ffmpeg args
    cmd = [
        "ffmpeg",
        "-i", file,
        "-ar", str(stream_sr),
        "-ac", "2",
    ]

    # Apply loudness normalization ONLY for WAVs
    if ext == ".wav":
        cmd += [
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"
        ]

    # Output raw float32 PCM to stdout
    cmd += [
        "-f", "f32le",
        "pipe:1"
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True
    )

    raw = proc.stdout

    # Convert to NumPy array
    data = np.frombuffer(raw, dtype=np.float32).copy()

    # Ensure stereo
    if data.size % 2 != 0:
        raise RuntimeError("Audio stream is not stereo-aligned")

    data = data.reshape(-1, 2)
    info = get_track_info(file, os.path.basename(file))
    return info, data

def format_time(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

# --------------------------
# Playlist system
# --------------------------
playlists = {}
current_playlist = []
current_playlist_name = None
current_index = 0

def load_playlists_from_json(json_file):
    global playlists
    if not os.path.exists(json_file):
        print(f"[ERROR] Playlist JSON '{json_file}' not found.")
        return
    with open(json_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    playlists = {}
    for name, content in raw.items():
        if isinstance(content, dict) and "folder" in content:
            folder = content["folder"]
            if os.path.exists(folder):
                tracks = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                          if f.lower().endswith(('.wav', '.flac', '.mp3', '.m4a'))]
                if tracks:
                    playlists[name] = tracks
        elif isinstance(content, list):
            tracks = [f for f in content if os.path.exists(f) and f.lower().endswith(('.wav', '.flac', '.mp3', '.m4a'))]
            if tracks:
                playlists[name] = tracks
        else:
            print(f"[WARN] Ignoring invalid playlist '{name}'")

def select_playlist(name):
    global current_playlist, current_playlist_name, current_index
    if name not in playlists:
        print(f"[ERROR] Playlist '{name}' not found.")
        return
    current_playlist = playlists[name]
    current_playlist_name = name
    current_index = 0
    print(f"[PLAYLIST] Switched to '{name}' with {len(current_playlist)} tracks")
    queue_song(current_index)

# --------------------------
# Playback state
# --------------------------
paused = False
playing_song = {"data": None, "pos": 0, "name": "", "preloaded": None}
playing_lock = threading.Lock()

# --------------------------
# Playback functions
# --------------------------
def queue_song(index):
    global playing_song
    if not current_playlist:
        print("[ERROR] No playlist loaded.")
        return
    if shuffle_mode and not random_any_mode:
        index = random.randint(0, len(current_playlist) - 1)
    info, data = load_audio_ffmpeg(current_playlist[index])
    with playing_lock:
        playing_song["data"] = data
        playing_song["pos"] = 0
        playing_song["name"] = os.path.basename(current_playlist[index])
        playing_song["title"] = info["title"]
        playing_song["artist"] = info["artist"]
    print(f"[[QUEUE]]] {os.path.basename(current_playlist[index])} (index {index})")
    preload_next(index)

def preload_next(index):
    global preload_song_metadata
    if not current_playlist or random_any_mode:
        return
    next_index = (index + 1) % len(current_playlist)
    info, data = load_audio_ffmpeg(current_playlist[index])
    with playing_lock:
        playing_song["preloaded"] = {
            "data": data,
            "name": os.path.basename(current_playlist[next_index]),
            "index": next_index
        }
    preload_song_metadata = info
    print(f"[PRELOAD DONE] idx={next_index} -> {os.path.basename(current_playlist[next_index])}")

def play_next():
    global current_index
    if random_any_mode:
        all_tracks = [t for plist in playlists.values() for t in plist]
        if not all_tracks:
            print("[ERROR] No tracks anywhere.")
            return
        choice = random.choice(all_tracks)
        info, data = load_audio_ffmpeg(choice)
        with playing_lock:
            playing_song["data"] = data
            playing_song["pos"] = 0
            playing_song["name"] = info["title"]
        print(f"[RANDOM-ANY] {playing_song['name']}")
        return
    if shuffle_mode:
        current_index = random.randint(0, len(current_playlist) - 1)
    else:
        current_index = (current_index + 1) % len(current_playlist)
    queue_song(current_index)

def play_prev():
    global current_index
    current_index = (current_index - 1) % len(current_playlist)
    queue_song(current_index)

def toggle_pause():
    global paused
    paused = not paused
    print("Paused" if paused else "Resumed")

def seek_seconds(seconds):
    global playing_song
    need_next = False
    with playing_lock:
        if playing_song["data"] is None:
            return
        new_pos = playing_song["pos"] + int(seconds * stream_sr)
        if new_pos < 0:
            playing_song["pos"] = 0
        elif new_pos >= playing_song["data"].shape[0]:
            need_next = True
        else:
            playing_song["pos"] = new_pos
            print(f"[SEEK] moved to {format_time(playing_song['pos']/stream_sr)}")
    if need_next:
        play_next()

def change_volume(delta):
    global master_gain
    master_gain = max(0.0, master_gain + delta)
    print(f"[VOLUME] master_gain={master_gain:.2f}")

# --------------------------
# Status printer
# --------------------------
def status():
    with playing_lock:
        if playing_song["data"] is not None:
            if status_enabled:
                pos = playing_song["pos"]
                total = playing_song["data"].shape[0]
                if debug_status_enabled:                    
                    perc = pos / total * 100
                    pre = playing_song["preloaded"]
                    pre_info = f"idx={pre['index']} name={pre['name']}" if pre else "None"
                    print(f"[STATUS] pl={current_playlist_name} idx={current_index} name={playing_song['name']} "
                        f"pos={format_time(pos/stream_sr)}/{format_time(total/stream_sr)} ({perc:.0f}%) "
                        f"| paused={paused} shuffle={shuffle_mode} random={random_any_mode} | preloaded {pre_info}")
                else:
                    print(f"[red]{current_playlist_name}[white]/[green]{playing_song['title']}"
                            f"\n[white]by [blue]{playing_song['artist']}"
                            f"\n[red]{format_time(pos/stream_sr)}[white]/[red]{format_time(total/stream_sr)}"
                            f"\n[red]Shuffle: [green]{'on' if shuffle_mode == True else 'off'}\n[red]Random-Any: [green]{'on' if random_any_mode == True else 'off'}")

# --------------------------
# Control loop (numpad)
# --------------------------
def control_loop():
    global shuffle_mode, random_any_mode
    while True:
        if keyboard.is_pressed(83):  # So that music player operations don't act weirdly with normal numpad functions.
            if is_numlock_on() and keyboard.is_pressed('num 7'):
                play_prev()
                while keyboard.is_pressed('num 7'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 8'):
                toggle_pause()
                while keyboard.is_pressed('num 8'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 9'):
                play_next()
                while keyboard.is_pressed('num 9'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num /'):
                shuffle_mode = not shuffle_mode
                print("Shuffle mode:", shuffle_mode)
                while keyboard.is_pressed('num /'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num *'):
                random_any_mode = not random_any_mode
                print("Random-anywhere mode:", random_any_mode)
                while keyboard.is_pressed('num *'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 4'):
                seek_seconds(-10)
                while keyboard.is_pressed('num 4'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 1'):
                seek_seconds(-30)
                while keyboard.is_pressed('num 1'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 6'):
                seek_seconds(10)
                while keyboard.is_pressed('num 6'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 3'):
                seek_seconds(30)
                while keyboard.is_pressed('num 3'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 5'):
                change_volume(gain_step)
                while keyboard.is_pressed('num 5'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 2'):
                change_volume(-gain_step)
                while keyboard.is_pressed('num 2'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num -'):
                status_enable = not status_enable
        time.sleep(0.05)

# --------------------------
# CLI loop (stdin commands)
# --------------------------
def cli_loop():
    global shuffle_mode, random_any_mode, master_gain
    while True:
        try:
            cmd = input(">> ").strip().lower()
        except EOFError:
            break

        if cmd in ("q", "quit", "exit"):
            print("[CLI] Exiting...")
            os._exit(0)

        elif cmd.startswith("playlist "):
            name = cmd.split(" ", 1)[1].strip()
            select_playlist(name)

        elif cmd == "playlists":
            print("[CLI] Playlists:", ", ".join(playlists.keys()))

        elif cmd == "shuffle":
            shuffle_mode = not shuffle_mode
            print(f"[CLI] Shuffle mode = {shuffle_mode}")

        elif cmd == "random":
            random_any_mode = not random_any_mode
            print(f"[CLI] Random-anywhere mode = {random_any_mode}")

        elif cmd == "next":
            play_next()

        elif cmd == "prev":
            play_prev()

        elif cmd == "pause":
            toggle_pause()

        elif cmd == "reload":
            load_playlists_from_json(playlist_json)

        elif cmd.startswith("vol "):
            try:
                master_gain = float(cmd.split()[1])
            except Exception as e:
                print(f"[CLI] Error {e} occurred.")

        elif cmd == "status":
            status()

        else:
            print("[CLI] Unknown command:", cmd)

# --------------------------
# Playback loop
# --------------------------
def playback_loop(device1, device2):
    global playing_song, paused
    with sd.OutputStream(device=device1, channels=stream_channels,
                         samplerate=stream_sr, blocksize=blocksize) as s1, \
         sd.OutputStream(device=device2, channels=stream_channels,
                         samplerate=stream_sr, blocksize=blocksize) as s2:
        while True:
            if playing_song["data"] is None or paused:
                time.sleep(0.05)
                continue

            need_next = False
            with playing_lock:
                pos = playing_song["pos"]
                data = playing_song["data"]
                chunk = data[pos:pos+blocksize]
                chunk_len = chunk.shape[0]

                if chunk_len < blocksize:
                    pad = np.zeros((blocksize - chunk_len, stream_channels), dtype='float32')
                    chunk = np.vstack([chunk, pad])

                chunk *= master_gain
                playing_song["pos"] += chunk_len

                if playing_song["pos"] >= data.shape[0]:
                    need_next = True

            s1.write(chunk)
            s2.write(chunk)

            if need_next:
                play_next()

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    load_playlists_from_json(playlist_json)

    if playlists:
        first_playlist = list(playlists.keys())[0]
        select_playlist(first_playlist)
    else:
        print("[ERROR] No playlists found. Exiting.")
        exit(1)

    print("Available devices:")
    for i, dev in enumerate(sd.query_devices()):
        print(f"{i}: {dev['name']} ({'input' if dev['max_input_channels']>0 else 'output'})")

    dev1 = int(input("Enter device index for output 1: "))
    dev2 = int(input("Enter device index for output 2: "))

    print("Controls: Numpad7=prev, Numpad8=pause/play, Numpad9=next, / = shuffle toggle, * = random-any toggle")
    print("Seek: Numpad4=-10s, Numpad1=-30s, Numpad6=+10s, Numpad3=+30s")
    print("Volume: Numpad5=up, Numpad2=down")
    print("CLI commands: playlists, playlist NAME, next, prev, pause, shuffle, random, vol +/-")

    threading.Thread(target=control_loop, daemon=True).start()
    threading.Thread(target=playback_loop, args=(dev1, dev2), daemon=True).start()
    threading.Thread(target=cli_loop, daemon=True).start()

    keyboard.wait("F12")
    print("Exited cleanly.")
