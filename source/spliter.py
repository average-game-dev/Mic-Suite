import sounddevice as sd
from keymods import capslock_on

toggler = False

# Configure devices
print("=== Devices ===")
for idx, d in enumerate(sd.query_devices()):
    print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")

input_device = int(input("Enter your input device ID: "))
output_device1 = int(input("Enter output1 device ID: "))
output_device2 = int(input("Enter output2 device ID: "))

samplerate = 44100
blocksize = 1024

# Per-channel gain (0.0 = silence, 1.0 = base)
gain1 = 1
gain2 = 1

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
    
    # Apply gain per output
    out1 = indata * gain1
    out2 = indata * gain2

    # Always write to output1
    stream1.write(out1)

    # Only write to output2 if Caps Lock XOR'd by toggler is True
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
