import signal
import sounddevice as sd
import numpy as np
import threading
from keymods import scrolllock_on
from PySide6 import QtWidgets, QtCore, QtGui
import time
import sys
from collections import deque

# ---------------- Globals & Thread-safety ----------------
MIC_GAIN = 1.0
mic_gain_lock = threading.Lock()

volume = 0.0
volume_lock = threading.Lock()

mic_on = True
mic_lock = threading.Lock()

mic_queue = deque()  # holds incoming chunks
mic_queue_lock = threading.Lock()

stop_event = threading.Event()

def handle_sigint(signum, frame):
    stop_event.set()
    QtWidgets.QApplication.quit()

# helpers

def scroll_lock_updater():
    global mic_on
    last_state = True

    while not stop_event.is_set():
        new_state = not scrolllock_on()

        if new_state != last_state:
            with mic_lock:
                mic_on = new_state

            if not new_state:
                # FLUSH ALL AUDIO
                with mic_queue_lock:
                    mic_queue.clear()
                ring_buffer.clear()

        last_state = new_state
        time.sleep(0.01)

# UI

def rgb(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

class MeterOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        self.resize(360, 24)
        self.move(50, 50)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(30)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        with volume_lock:
            vol = volume

        with mic_lock:
            on = mic_on

        fill = int(min(max(vol * 1000.0, 0.0), 360))

        if on:
            color = (
                QtGui.QColor(10, 255, 18) if vol < 0.2 else
                QtGui.QColor(255, 218, 10) if vol < 0.4 else
                QtGui.QColor(255, 10, 10)
            )
        else:
            color = (
                QtGui.QColor(10, 155, 118) if vol < 0.2 else
                QtGui.QColor(255, 118, 110) if vol < 0.4 else
                QtGui.QColor(255, 10, 110)
            )

        painter.fillRect(0, 0, fill, 24, color)

# ---------------- Audio callbacks ----------------
def mic_callback(indata, frames, time_info, status):
    if status:
        print("Mic callback status:", status, file=sys.stderr)

    with mic_lock:
        if not mic_on:
            return  # drop input ONLY when muted

    with mic_gain_lock:
        gain = MIC_GAIN

    chunk = indata.copy() * gain

    with mic_queue_lock:
        mic_queue.append(chunk)

    global volume
    with volume_lock:
        volume_val = float(np.sqrt(np.mean(chunk**2)))
        volume = max(volume_val, volume * 0.9)

# Ring buffer for leftover samples
ring_buffer = deque()

def out_callback(outdata, frames, time_info, status):
    global ring_buffer

    if status:
        print("Out callback status:", status, file=sys.stderr)

    with mic_lock:
        muted = not mic_on

    if muted:
        with mic_queue_lock:
            mic_queue.clear()
        ring_buffer.clear()
        outdata[:] = 0
        return

    chunks = []
    total = 0

    with mic_queue_lock:
        while ring_buffer and total < frames:
            c = ring_buffer.popleft()
            chunks.append(c)
            total += len(c)

        while mic_queue and total < frames:
            c = mic_queue.popleft()
            chunks.append(c)
            total += len(c)

    if chunks:
        chunk = np.concatenate(chunks, axis=0)
    else:
        chunk = np.zeros((frames, 1), dtype='float32')

    if chunk.shape[0] < frames:
        chunk = np.pad(chunk, ((0, frames - chunk.shape[0]), (0, 0)))

    outdata[:] = chunk[:frames]

    leftover = chunk[frames:]
    if len(leftover):
        ring_buffer.append(leftover)


# ---------------- Command loop ----------------
def command_loop():
    global MIC_GAIN
    print("Commands: gain <float>, help, quit")

    while not stop_event.is_set():
        try:
            line = sys.stdin.readline()
            if not line:  # EOF
                stop_event.set()
                break
        except KeyboardInterrupt:
            stop_event.set()
            break

        cmd = line.strip()

        if cmd == "":
            continue

        if cmd == "quit":
            stop_event.set()
            break

        elif cmd.startswith("gain"):
            parts = cmd.split(maxsplit=1)
            if len(parts) != 2:
                print("Usage: gain <float>")
                continue
            try:
                with mic_gain_lock:
                    MIC_GAIN = float(parts[1])
                print(f"MIC_GAIN set to {MIC_GAIN}")
            except ValueError:
                print("Invalid gain")

        elif cmd == "help":
            print("gain <float> — set mic gain")
            print("quit — exit")

        else:
            print("Unknown command")


# ---------------- Main ----------------
def main():
    print("=== Devices ===")
    for idx, d in enumerate(sd.query_devices()):
        print(f"[{idx}] {d['name']} (I/O: {d['max_input_channels']}/{d['max_output_channels']}) ({d['hostapi']})")

    try:
        mic_id = int(input("Enter your mic device ID: "))
        out_id = int(input("Enter output device ID: "))
    except Exception as e:
        print("Invalid device id:", e)
        return

    samplerate = 48000
    blocksize = 256  # small blocksize for low latency

    try:
        in_stream = sd.InputStream(samplerate=samplerate, device=mic_id, channels=1,
                                   blocksize=blocksize, callback=mic_callback,
                                   dtype='float32', latency='low')
        out_stream = sd.OutputStream(samplerate=samplerate, device=out_id, channels=1,
                                     blocksize=blocksize, callback=out_callback,
                                     dtype='float32', latency='low')
        in_stream.start()
        out_stream.start()
    except Exception as e:
        print("Failed to start streams:", e)
        return

    scroll_lock_updater_thread = threading.Thread(target=scroll_lock_updater, daemon=True)
    scroll_lock_updater_thread.start()

    cmd_thread = threading.Thread(target=command_loop, daemon=True)
    cmd_thread.start()

    app = QtWidgets.QApplication(sys.argv)

    signal.signal(signal.SIGINT, handle_sigint)

    overlay = MeterOverlay()
    overlay.show()

    try:
        app.exec()
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
