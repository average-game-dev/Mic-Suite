import os
import threading
import queue
import subprocess
import sounddevice as sd
import soundfile as sf
import numpy as np
import keyboard
from collections import deque
import ctypes
import json
import random
from keymods import is_numlock_on

# --------------------------
# Settings (tweakable)
# --------------------------
stream_sr = 48000
stream_channels = 2
blocksize = 1024  # preferred frames per callback
master_gain = 1.0  # default master gain

# --------------------------
# Lock and stuff
# --------------------------
audio_engine_alive = False

# --------------------------
# Audio file preprocessing (ffmpeg)
# --------------------------
def ffmpeg_resample_and_normalize(input_file, output_file, target_sr=48000):
    temp_resampled = output_file.replace("_normalized.wav", "_resampled.wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_file,
        "-ar", str(target_sr), "-ac", "2", "-c:a", "pcm_f32le", temp_resampled
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    subprocess.run([
        "ffmpeg", "-y", "-i", temp_resampled,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", str(target_sr), "-ac", "2", "-c:a", "pcm_f32le", output_file
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    os.remove(temp_resampled)

def prepare_audio_hq(file, target_sr=48000):
    base, ext = os.path.splitext(file)
    temp_file = f"{base}_{target_sr}hz_normalized.wav"
    if not os.path.exists(temp_file):
        print(f"Resampling and normalizing: {file}")
        ffmpeg_resample_and_normalize(file, temp_file, target_sr)
    return temp_file

def load_and_prepare_audio(file):
    data, sr = sf.read(file, dtype='float32')
    # ensure stereo
    if data.ndim == 1:
        data = np.column_stack([data, data])
    if sr != stream_sr:
        raise RuntimeError(f"Sample rate mismatch in {file}: {sr} Hz")
    return data, sr

# --------------------------
# Your mapping / files
# --------------------------
numpad_map = {
    82: 0, 79: 1, 80: 2, 81: 3, 75: 4,
    76: 5, 77: 6, 71: 7, 72: 8, 73: 9,
}
numpad_stop_code = 55
numpad_plus_code = 78
numpad_minus_code = 74
numpad_enter_code = 28
numpad_del_code = 83
manual_files = {}

def load():
    with open("sounds.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    for key in data["manual_files"].keys():
        manual_files[int(key)] = data["manual_files"][key]

# --------------------------
# Runtime audio structures
# --------------------------
audios = {}  # index -> {"data": `np.array, "sr": int, "gain": float}
play_queue = queue.Queue()  # place requests here
playing_sounds = []  # list of dicts: {"data":..., "pos":int, "gain":float}
playing_lock = threading.Lock()

# small cache of last produced mixed chunks from master callback for slave to consume
slave_buffer = deque(maxlen=256)  # holds np arrays of shape (frames,channels)
slave_buffer_lock = threading.Lock()

# --------------------------
# Playback utilities
# --------------------------
def play_sound(data, gain=1.0):
    """Queue a sound to play (data is the numpy float32 stereo array)."""
    play_queue.put({'data': data, 'gain': gain})

def num_pad_handler(num_pad_num):
    if not keyboard.is_pressed(83):
        if (keyboard.is_pressed(numpad_plus_code) and keyboard.is_pressed(numpad_minus_code)) and audios.get(num_pad_num + 40):
            idx = num_pad_num + 40
        elif (keyboard.is_pressed(numpad_minus_code) and keyboard.is_pressed(numpad_enter_code)) and audios.get(num_pad_num + 50):
            idx = num_pad_num + 50
        elif (keyboard.is_pressed(numpad_plus_code) and keyboard.is_pressed(numpad_enter_code)) and audios.get(num_pad_num + 60):
            idx = num_pad_num + 60
        elif keyboard.is_pressed(numpad_enter_code) and audios.get(num_pad_num + 30):
            idx = num_pad_num + 30
        elif keyboard.is_pressed(numpad_plus_code) and audios.get(num_pad_num + 10):
            idx = num_pad_num + 10
        elif keyboard.is_pressed(numpad_minus_code) and audios.get(num_pad_num + 20):
            idx = num_pad_num + 20
        else:
            idx = num_pad_num

        if idx == 33:
            number = random.randint(0, 9)
            play_sound(audios[200 + number]["data"], audios[200 + number]["gain"])
            print(f"playing {200 + number}")
        else:
            if audios.get(idx):
                play_sound(audios[idx]["data"], audios[idx]["gain"])
                print(f"playing {idx}")
            else:
                print(f"num_pad_{idx} is None.")

def on_key(event):
    if is_numlock_on():
        if event.event_type != 'down':
            return
        if event.scan_code == numpad_stop_code:
            print("Stopping all sounds immediately.")
            with playing_lock:
                playing_sounds.clear()
            with slave_buffer_lock:
                slave_buffer.clear()
            # let callbacks output silence naturally
            return

        if event.scan_code in numpad_map:
            num_pad_handler(numpad_map[event.scan_code])

# --------------------------
# The master mixing callback
# --------------------------
def master_callback(outdata, frames, time_info, status):
    """
    This is called by sounddevice for the primary output device.
    It mixes the currently-playing sounds into 'outdata' and advances positions.
    It also stores a copy into slave_buffer for the secondary device to play.
    """
    global master_gain
    if status:
        # You can inspect status for underrun warnings
        # print("Master status:", status)
        pass

    # attempt to pull new play requests (non-blocking)
    try:
        while True:
            req = play_queue.get_nowait()
            with playing_lock:
                playing_sounds.append({'data': req['data'], 'pos': 0, 'gain': req.get('gain', 1.0)})
    except queue.Empty:
        pass

    # create output buffer
    out = np.zeros((frames, stream_channels), dtype='float32')

    with playing_lock:
        finished_indices = []
        for i, s in enumerate(playing_sounds):
            data = s['data']
            pos = s['pos']
            gain = s['gain'] * master_gain

            # slice requested frames
            chunk = data[pos:pos + frames]
            chunk_len = chunk.shape[0]

            if chunk_len == 0:
                finished_indices.append(i)
                continue

            if chunk_len < frames:
                # pad the remainder with zeros
                pad = np.zeros((frames - chunk_len, stream_channels), dtype='float32')
                chunk = np.vstack([chunk, pad])
                finished_indices.append(i)

            # mix (additive)
            out[:chunk.shape[0]] += chunk * gain
            # advance position by actual samples consumed
            s['pos'] += chunk_len

        # remove finished entries (in reverse order)
        for idx in reversed(finished_indices):
            del playing_sounds[idx]

    # final clipping to avoid distortion
    np.clip(out, -1.0, 1.0, out=out)

    # write to outdata (this is the buffer the sounddevice will output)
    outdata[:] = out

    # also push a copy for the slave to consume
    with slave_buffer_lock:
        # keep small copies, don't grow memory
        slave_buffer.append(out.copy())

# --------------------------
# The slave callback (secondary device)
# --------------------------
def slave_callback(outdata, frames, time_info, status):
    """
    Secondary device callback. It consumes the mixed chunks produced by master callback.
    If empty, it outputs silence (prevents blocking).
    """
    if status:
        # print("Slave status:", status)
        pass

    with slave_buffer_lock:
        if len(slave_buffer) > 0:
            chunk = slave_buffer.popleft()
            # If frames differ (unlikely), handle it:
            if chunk.shape[0] == frames:
                outdata[:] = chunk
            elif chunk.shape[0] > frames:
                outdata[:] = chunk[:frames]
                # If there's leftover, push the remainder back front
                remainder = chunk[frames:]
                slave_buffer.appendleft(remainder)
            else:
                # chunk shorter than frames -> pad
                pad = np.zeros((frames - chunk.shape[0], stream_channels), dtype='float32')
                out = np.vstack([chunk, pad])
                outdata[:] = out
        else:
            # no mixed chunk ready -> silence
            outdata[:] = np.zeros((frames, stream_channels), dtype='float32')

# -------------------------
# Audio Engine
# -------------------------
def pick_devices():
    global dev1, dev2
    print("=== Output Devices ===")
    devs = sd.query_devices()
    for idx, d in enumerate(devs):
        if d['max_output_channels'] > 0:
            print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) "
                  f"(I/O: {d['max_input_channels']}/{d['max_output_channels']})")
    try:
        dev1 = int(input("Primary output device ID: ").strip())
        dev2 = int(input("Secondary output device ID (loopback/mic): ").strip())
    except ValueError:
        print("Invalid device ID.")
        exit(1)
        
def create_streams():
    global stream_master, stream_slave
    try:
        stream_master = sd.OutputStream(
            samplerate=stream_sr,
            channels=stream_channels,
            device=dev1,
            dtype='float32',
            blocksize=blocksize,
            callback=master_callback
        )

        stream_slave = sd.OutputStream(
            samplerate=stream_sr,
            channels=stream_channels,
            device=dev2,
            dtype='float32',
            blocksize=blocksize,
            callback=slave_callback
        )
    except Exception as e:
        print("Failed to create streams:", e)
        raise

def start_streams():
    global stream_master, stream_slave
    try:
        stream_master.start()
        stream_slave.start()
    except Exception as e:
        print("Failed to start streams:", e)
        raise

def start_streams():
    global stream_master, stream_slave
    try:
        stream_master.start()
        stream_slave.start()
    except Exception as e:
        print("Failed to start streams:", e)
        raise

def start_audio_threads():
    threading.Thread(target=gain_control_loop, daemon=True).start()
    keyboard.hook(on_key)

def start_audio_engine():
    global audio_engine_alive

    if audio_engine_alive:
        print("audio engine already running")
        return

    pick_devices()        # user chooses devices
    create_streams()
    start_streams()
    start_audio_threads()

    audio_engine_alive = True

def stop_audio_engine():
    global stream_master, stream_slave, audio_engine_alive
    print("Stopping audio engine...")

    try:
        if stream_master:
            stream_master.stop()
            stream_master.close()
            stream_master = None
    except Exception as e:
        print("Master stop error:", e)

    try:
        if stream_slave:
            stream_slave.stop()
            stream_slave.close()
            stream_slave = None
    except Exception as e:
        print("Slave stop error:", e)

    with playing_lock:
        playing_sounds.clear()

    with slave_buffer_lock:
        slave_buffer.clear()

    try:
        play_queue.queue.clear()
    except Exception:
        pass

    audio_engine_alive = False  # ← reset so hard reload can start it again
    print("Audio engine fully stopped.")

# --------------------------
# Gain control thread (CLI)
# --------------------------
def gain_control_loop():
    global master_gain
    while True:
        try:
            cmd = input(">> ").strip().lower()
        except EOFError:
            break
        if not cmd:
            continue
        if cmd.startswith("master "):
            try:
                master_gain = float(cmd.split()[1])
                print(f"Master gain set to {master_gain}")
            except ValueError:
                print("Invalid master gain value.")
        elif cmd.startswith("gain "):
            try:
                _, idx_str, gain_str = cmd.split()
                idx = int(idx_str)
                gain = float(gain_str)
                if audios.get(idx):
                    audios[idx]["gain"] = gain
                    print(f"Set gain of {idx} to {gain}")
                else:
                    print(f"No sound at index {idx}")
            except Exception as e:
                print(f"Error setting gain: {e}")
        elif cmd.startswith("reload "):
            mode = cmd.split()[1]
            
            reload(mode)
                
        else:
            print("Commands: master <value>, gain <index> <value>")

# --------------------------
# Audio reload helper
# --------------------------
def reload_audio_files():
    """
    Loads/resamples/normalizes all audio files from manual_files into `audios`.
    Handles slots 200-209 and 0-69.
    """
    # Reload 200–209
    for i in range(10):
        file = manual_files.get(i + 200)
        if not file or not os.path.exists(file):
            print(f"missing file for slot {i + 200}: {file}")
            continue
        norm = prepare_audio_hq(file)
        data, sr = load_and_prepare_audio(norm)
        audios[i + 200] = {"data": data, "sr": sr, "gain": 1.0}
        print(f"Reloaded num_pad_{i + 200}: {file}")

    # Reload 0–69
    for i in range(70):
        file = manual_files.get(i)
        if file and os.path.exists(file):
            norm = prepare_audio_hq(file)
            data, sr = load_and_prepare_audio(norm)
            audios[i] = {"data": data, "sr": sr, "gain": audios.get(i, {}).get("gain", 1.0)}
            print(f"Reloaded num_pad_{i}: {file}")
        else:
            audios[i] = None

# --------------------------
# Reloaders
# --------------------------
def reload_soft():
    print("Soft reloading sounds...")

    # Stop playback
    with playing_lock:
        playing_sounds.clear()

    with slave_buffer_lock:
        slave_buffer.clear()

    # Reload JSON
    manual_files.clear()
    load()

    # Reload audio
    reload_audio_files()

    print("Soft reload complete.")

def reload_hard():
    print("Hard reloading audio engine...")

    # Stop everything
    stop_audio_engine()

    # Reload JSON and audio files
    manual_files.clear()
    load()
    reload_audio_files()

    # Pick devices again
    pick_devices()

    # Re-create and start streams
    create_streams()
    start_streams()

    print("Hard reload complete.")

# Update reload dispatcher
def reload(mode):
    if mode == "soft":
        reload_soft()
    elif mode == "hard":
        reload_hard()
    else:
        print(f"Unknown reload mode: {mode}")

# --------------------------
# Device chooser
# --------------------------
def choose_output_devices():
    print("=== Output Devices ===")
    devs = sd.query_devices()
    for idx, d in enumerate(devs):
        if d['max_output_channels'] > 0:
            print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")
    try:
        d1 = int(input("Primary output device ID: ").strip())
        d2 = int(input("Secondary output device ID (loopback/mic): ").strip())
        return d1, d2
    except ValueError:
        print("Invalid device ID.")
        exit(1)

# --------------------------
# Main
# --------------------------
def main():
    # Load JSON file and manual_files
    load()

    # Preload a selection of sounds (200-209)
    for i in range(10):
        file = manual_files.get(i + 200)
        if not file or not os.path.exists(file):
            print(f"missing file for slot {i + 200}: {file}")
            continue
        norm = prepare_audio_hq(file)
        data, sr = load_and_prepare_audio(norm)
        audios[i + 200] = {"data": data, "sr": sr, "gain": 1.0}
        print(f"Loaded num_pad_{i + 200}: {file}")

    # Preload normal slots 0-69
    for i in range(70):
        file = manual_files.get(i)
        if file and os.path.exists(file):
            norm = prepare_audio_hq(file)
            data, sr = load_and_prepare_audio(norm)
            audios[i] = {"data": data, "sr": sr, "gain": 1.0}
            print(f"Loaded num_pad_{i}: {file}")
        else:
            audios[i] = None

    # Start the audio engine (device selection + streams + threads)
    start_audio_engine()

    print("Press numpad 0-9 to play sounds. Use +, -, and Enter for alt slots. Press * to stop. F12 to quit.")

    # Wait for F12 to exit
    keyboard.wait('F12')

    # Cleanup on exit
    stop_audio_engine()
    print("Exited cleanly.")


main()