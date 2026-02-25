import sounddevice as sd
from keymods import capslock_on
import threading
from effects import EFFECTS, EFFECT_PARAMS

toggler = False

# Configure devices
print("=== Devices ===")
for idx, d in enumerate(sd.query_devices()):
    print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")

input_device = int(input("Enter your input device ID: "))
output_device1 = int(input("Enter output1 device ID: "))
output_device2 = int(input("Enter output2 device ID: "))

samplerate = 48000
blocksize = 1024

# Per-channel gain (0.0 = silence, 1.0 = base)
gain1 = 1
gain2 = 1

# ---------------- Effect System ----------------
EFFECT_ENABLED = False
CURRENT_EFFECT = None
effect_lock = threading.Lock()

def set_effect(fn):
    global CURRENT_EFFECT, EFFECT_ENABLED
    with effect_lock:
        CURRENT_EFFECT = fn
        EFFECT_ENABLED = fn is not None

def process_effect(chunk):
    with effect_lock:
        if not EFFECT_ENABLED or CURRENT_EFFECT is None:
            return chunk
        return CURRENT_EFFECT(chunk)

# Open output streams
stream1 = sd.OutputStream(
    device=output_device1, channels=1, samplerate=samplerate, blocksize=blocksize
)
stream2 = sd.OutputStream(
    device=output_device2, channels=1, samplerate=samplerate, blocksize=blocksize
)

def callback(indata, frames, time, status):        
    global gain1, gain2

    if status:
        print(status)

    # Copy to avoid touching original buffer
    chunk = indata.copy()

    # ---- Apply effect FIRST ----
    chunk = process_effect(chunk)

    # ---- Apply gain per output ----
    out1 = chunk * gain1
    out2 = chunk * gain2

    # ---- Route outputs ----
    stream1.write(out1)

    if capslock_on() != toggler:
        stream2.write(out2)


with stream1, stream2:
    with sd.InputStream(device=input_device, channels=1, samplerate=samplerate,
                        blocksize=blocksize, callback=callback):
        print("Streaming... Caps Lock controls output2")
        try:
            while True:
                cmd = input("> ")
                cmds = cmd.split()

                if cmds[0] == "gain":
                    if cmds[1] == "primary" or cmds[1] == "1":
                        gain1 = float(cmds[2])
                    if cmds[1] == "secondary" or cmds[1] == "2":
                        gain2 = float(cmds[2])
                    if cmds[1] == "both" or cmds[1] == "0":
                        gain1 = float(cmds[2])
                        gain2 = float(cmds[2])
                elif cmds[0] == "toggle":
                    toggler = not toggler


        except KeyboardInterrupt:
            print("Stopped")
