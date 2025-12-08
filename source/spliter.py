import sounddevice as sd
import ctypes

# Windows function to check key state
def capslock_on():
    return ctypes.windll.user32.GetKeyState(0x14) & 1 != 0

# Configure devices
print("=== Devices ===")
for idx, d in enumerate(sd.query_devices()):
    print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")

input_device = int(input("Enter your input device ID: "))
output_device1 = int(input("Enter output1 device ID: "))
output_device2 = int(input("Enter output2 device ID: "))

samplerate = 44100
blocksize = 1024

# Per-channel gain (0.0 = silence, 1.0 = unity)
gain1 = 1
gain2 = 3

# Open output streams
stream1 = sd.OutputStream(
    device=output_device1, channels=1, samplerate=samplerate, blocksize=blocksize
)
stream2 = sd.OutputStream(
    device=output_device2, channels=1, samplerate=samplerate, blocksize=blocksize
)

def callback(indata, frames, time, status):
    if status:
        print(status)
    
    # Apply gain per output
    out1 = indata * gain1
    out2 = indata * gain2

    # Always write to output1
    stream1.write(out1)

    # Only write to output2 if Caps Lock is on
    if capslock_on():
        stream2.write(out2)

with stream1, stream2:
    with sd.InputStream(device=input_device, channels=1, samplerate=samplerate,
                        blocksize=blocksize, callback=callback):
        print("Streaming... Caps Lock controls output2")
        try:
            while True:
                sd.sleep(1000)
        except KeyboardInterrupt:
            print("Stopped")
