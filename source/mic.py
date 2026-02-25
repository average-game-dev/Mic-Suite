import signal
import sounddevice as sd
import numpy as np
import threading
from keymods import scrolllock_on
from PySide6 import QtWidgets, QtCore, QtGui
import time
import sys
from collections import deque
from effects import EFFECTS, EFFECT_PARAMS


# ---------------- Globals & Thread-safety ----------------
MIC_GAIN = 1.0
mic_gain_lock = threading.Lock()

volume = 0.0
volume_lock = threading.Lock()

mic_on = True
mic_lock = threading.Lock()

stop_event = threading.Event()

# ---------------- Effect System ----------------
EFFECT_ENABLED = False
CURRENT_EFFECTS = [] # list of callables 
effect_lock = threading.Lock()

def set_effect(fns):
    """
    fns: list of effect functions, or None/[] to disable
    """
    global CURRENT_EFFECTS, EFFECT_ENABLED
    with effect_lock:
        if not fns:
            CURRENT_EFFECTS = []
            EFFECT_ENABLED = False
        else:
            CURRENT_EFFECTS = fns
            EFFECT_ENABLED = True

def process_effect(chunk):
    with effect_lock:
        if not EFFECT_ENABLED or not CURRENT_EFFECTS:
            return chunk

        out = chunk
        for fn in CURRENT_EFFECTS:
            out = fn(out)
        return out

# ---------------- Signal ----------------
def handle_sigint(signum, frame):
    stop_event.set()
    QtWidgets.QApplication.quit()

# ---------------- Scroll Lock ----------------
def scroll_lock_updater():
    global mic_on
    last_state = True

    while not stop_event.is_set():
        new_state = not scrolllock_on()

        if new_state != last_state:
            with mic_lock:
                mic_on = new_state

        last_state = new_state
        time.sleep(0.01)


# ---------------- UI ----------------
class MeterOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool |
            QtCore.Qt.WindowTransparentForInput
        )

        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
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

# ---------------- Audio ----------------
def duplex_callback(indata, outdata, frames, time_info, status):
    if status:
        print("Callback status:", status)

    with mic_lock:
        if not mic_on:
            outdata[:] = 0
            return

    with mic_gain_lock:
        gain = MIC_GAIN

    chunk = indata.copy() * gain

    # volume meter
    global volume
    with volume_lock:
        volume_val = float(np.sqrt(np.mean(chunk**2)))
        volume = max(volume_val, volume * 0.9)

    # apply effects
    chunk = process_effect(chunk)

    outdata[:] = chunk

# ---------------- Command Loop ----------------
def command_loop():
    global MIC_GAIN

    print("Commands: gain <float>, effect <name>, help, quit")

    while not stop_event.is_set():
        line = sys.stdin.readline()
        if not line:
            stop_event.set()
            break

        cmd = line.strip()

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

        elif cmd.startswith("effect"):
            if cmd.split()[1] == "param":
                if len(cmd.split()) < 4:
                    print("Error! To set a parameter you need at least four terms!")
                    continue
                parameter = cmd.split()[2]
                if parameter in EFFECT_PARAMS.keys():
                    try:
                        float(cmd.split()[3])
                    except Exception as e:
                        print("Error! You have to set the values of parameters to numbers or floats! No characters!")
                    EFFECT_PARAMS[parameter] = float(cmd.split()[3])
                    continue
                else:
                    print(f"Error! Effect Parameter {parameter} not found! Avaliable effects include {EFFECT_PARAMS.keys()}")
                    continue

            parts = cmd.split(maxsplit=1)
            if len(parts) != 2:
                print(f"Usage: effect <name[,name2,name3,...]|off>")
                continue

            arg = parts[1].lower()

            if arg == "off":
                set_effect(None)
                print("Effect disabled")
                continue

            names = [n.strip() for n in arg.split(",") if n.strip()]

            fns = []
            for n in names:
                fn = EFFECTS.get(n)
                if not fn:
                    print(f"Unknown effect: {n}")
                    print("Available:", ", ".join(EFFECTS.keys()))
                    fns = []
                    break
                fns.append(fn)

            if fns:
                set_effect(fns)
                print("Effect chain:", " -> ".join(names))

        elif cmd == "help":
            print("gain <float>")
            print(f"effect <{'|'.join(EFFECTS.keys())}|off>")
            print("quit")


        else:
            print("Unknown command")

# ---------------- Main ----------------
def main():
    print("=== Devices ===")    
    hostapis = sd.query_hostapis()
    devices = sd.query_devices()

    for idx, api in enumerate(hostapis):
        print(f"[{idx}] Host API: {api['name']}")
        for dev_id in api['devices']:
            dev = devices[dev_id]
            print(f"    [{dev_id}] {dev['name']} (I/O: {dev['max_input_channels']}/{dev['max_output_channels']})")
        print()
    try:
        mic_id = int(input("Enter your mic device ID: "))
        out_id = int(input("Enter output device ID: "))
    except Exception as e:
        print("Invalid device id:", e)
        return

    samplerate = 48000
    blocksize = 256

    try:
        stream = sd.Stream(
            samplerate=samplerate,
            blocksize=128,  # lower for latency
            device=(mic_id, out_id),
            channels=1,
            latency='low',
            dtype='float32',
            callback=duplex_callback
        )
        stream.start()
    except Exception as e:
        print("Failed to start stream:", e)
        return


    threading.Thread(target=scroll_lock_updater, daemon=True).start()
    threading.Thread(target=command_loop, daemon=True).start()

    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, handle_sigint)

    overlay = MeterOverlay()
    overlay.show()

    try:
        app.exec()
    finally:
        stop_event.set()
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

        print("Shutting down...")

if __name__ == "__main__":
    main()
