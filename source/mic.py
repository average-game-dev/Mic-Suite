import sounddevice as sd
import numpy as np
import queue
import ctypes
import threading
import sys
import tkinter as tk
import time
import msvcrt
from collections import deque

# ---------------- Globals & Thread-safety ----------------
MIC_GAIN = 1.5
mic_gain_lock = threading.Lock()

volume = 0.0
volume_lock = threading.Lock()

mic_on = True
mic_lock = threading.Lock()

mic_queue = deque(maxlen=5)  # holds last 20 chunks
mic_queue_lock = threading.Lock()
last_chunk = None
last_chunk_lock = threading.Lock()

stop_event = threading.Event()

# ---------------- Win32 / Tk helpers ----------------
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
WS_EX_TOOLWINDOW = 0x00000080  # hide from alt-tab / taskbar

def make_window_clickthrough(hwnd):
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

def scroll_lock_updater():
    while True:
        global mic_on
        with mic_lock:
            mic_on = not bool(ctypes.windll.user32.GetKeyState(0x91) & 1)
        time.sleep(0.01) # 10 ms

def rgb(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

# ---------------- Visual overlay (tkinter) ----------------
def create_overlay():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    # Use a color we will treat as transparent
    root.attributes('-transparentcolor', 'black')
    root.configure(bg='black')
    root.geometry('360x24+50+50')

    canvas = tk.Canvas(root, width=360, height=24, bg='black', highlightthickness=0)
    canvas.pack()

    # Make click-through
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    make_window_clickthrough(hwnd)

    def update_meter():
        with volume_lock:
            vol = volume
        canvas.delete("all")
        fill_len = int(min(max(vol * 1000.0, 0.0), 360))
        with mic_lock:
            if mic_on:
                if vol < 0.2:
                    color = rgb(10, 255, 18)
                elif vol < 0.4:
                    color = rgb(255, 218, 10)
                else:
                    color = rgb(255, 10, 10)
            else:
                if vol < 0.2:
                    color = rgb(10, 155, 118)
                elif vol < 0.4:
                    color = rgb(255, 118, 110)
                else:
                    color = rgb(255, 10, 110)
        # draw background faint bar (semi-visual guide)
        canvas.create_rectangle(0, 0, 360, 24, outline='', fill='')
        canvas.create_rectangle(0, 0, fill_len, 24, fill=color, outline='')
        if not stop_event.is_set():
            root.after(30, update_meter)  # schedule again
        else:
            try:
                root.destroy()
            except Exception:
                pass

    def check_stop():
        if stop_event.is_set():
            root.destroy()  # gracefully exit
        else:
            root.after(50, check_stop)  # check again in 50ms
            
    root.after(0, update_meter)
    return root

# ---------------- Audio callbacks ----------------
def mic_callback(indata, frames, time_info, status):
    if status:
        # print status in background thread to avoid blocking audio
        print("Mic callback status:", status, file=sys.stderr)
    # apply gain thread-safely
    with mic_gain_lock:
        gain = MIC_GAIN
    # make sure dtype is float32
    chunk = indata.copy().astype('float32') * float(gain)
    chunk = indata.copy() * gain
    with mic_queue_lock:
        mic_queue.append(chunk)
        # update a simple peak volume metric for meter
        global volume
        with volume_lock:
            # RMS / simple magnitude
            volume_val = float(np.sqrt(np.mean(chunk**2)))
            # smooth a bit by simple lowpass
            volume = max(volume_val, volume * 0.9)  # coarse smoothing

def out_callback(outdata, frames, time_info, status):
    global last_chunk
    if status:
        print("Out callback status:", status, file=sys.stderr)

    # When scroll lock is ON, bypass playback (i.e., silence)
    with mic_lock:
        if not mic_on:
            outdata[:] = np.zeros((frames, outdata.shape[1] if outdata.ndim > 1 else 1), dtype='float32')
            return

   # in out callback
    with mic_queue_lock:
        if mic_queue:
            chunk = mic_queue.popleft()
        else:
            chunk = np.zeros((frames, 1), dtype='float32')

    # Ensure chunk is 2D Nx1
    if chunk.ndim == 1:
        chunk = chunk.reshape(-1, 1)

    # Resample/pad/trim to requested frames
    if chunk.shape[0] < frames:
        chunk = np.pad(chunk, ((0, frames - chunk.shape[0]), (0, 0)))
    elif chunk.shape[0] > frames:
        # interpolate down/up to the requested number of frames
        x_old = np.arange(chunk.shape[0])
        x_new = np.linspace(0, chunk.shape[0] - 1, frames)
        chunk = np.interp(x_new, x_old, chunk[:, 0]).astype('float32').reshape(-1, 1)

    outdata[:] = chunk[:frames]

# ---------------- Command loop (background) ----------------
def command_loop():
    global MIC_GAIN
    print("Commands: gain <float>, help, quit")
    buffer = ""
    while not stop_event.is_set():
        if msvcrt.kbhit():
            char = msvcrt.getwche()
            if char in ('\r', '\n'):
                cmd = buffer.strip()
                buffer = ""
                if cmd == "quit":
                    stop_event.set()
                    break
                elif cmd.startswith("gain"):
                    try:
                        MIC_GAIN = float(cmd.split()[1])
                        print(f"MIC_GAIN set to {MIC_GAIN}")
                    except Exception:
                        print("Invalid gain")
                elif cmd == "help":
                    print("gain <float> — set mic gain")
                    print("quit — exit")
                else:
                    print("Unknown command")
            else:
                buffer += char
        else:
            time.sleep(0.01)

# ---------------- Main wiring ----------------
def main():
    # show devices first
    print("=== Devices ===")
    for idx, d in enumerate(sd.query_devices()):
        print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")

    try:
        mic_id = int(input("Enter your mic device ID: "))
        out_id = int(input("Enter output device ID: "))
    except Exception as e:
        print("Invalid device id:", e)
        return

    samplerate = 48000
    blocksize = 1024

    # create overlay in main thread
    root = create_overlay()

    # start audio streams non-blocking
    try:
        in_stream = sd.InputStream(samplerate=samplerate, device=mic_id, channels=1,
                                   blocksize=blocksize, callback=mic_callback, dtype='float32')
        out_stream = sd.OutputStream(samplerate=samplerate, device=out_id, channels=1,
                                     blocksize=blocksize, callback=out_callback, dtype='float32')
        in_stream.start()
        out_stream.start()
    except Exception as e:
        print("Failed to start streams:", e)
        return
    # start scroll lock updater
    scroll_lock_updater_thread = threading.Thread(target=scroll_lock_updater)
    scroll_lock_updater_thread.start()
    # start command loop in background
    cmd_thread = threading.Thread(target=command_loop, daemon=True)
    cmd_thread.start()

    # run tkinter mainloop (blocks here)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        try:
            in_stream.stop()
            in_stream.close()
        except Exception:
            pass
        try:
            out_stream.stop()
            out_stream.close()
        except Exception:
            pass
        print("Shutting down...")

if __name__ == "__main__":
    main()
