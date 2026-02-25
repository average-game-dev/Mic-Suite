import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import queue
import time

# -----------------------------
# Configuration
# -----------------------------
device1 = 1  # ID or name of first device (loopback)
device2 = 2  # ID or name of second device (USB mic)
samplerate = 48000  # Hz
duration = 30  # seconds
file_out = "dual_device.wav"

# -----------------------------
# Queues for buffering audio
# -----------------------------
q1 = queue.Queue()
q2 = queue.Queue()

# -----------------------------
# Callback functions
# -----------------------------
def callback1(indata, frames, time_info, status):
    if status:
        print("Device 1:", status)
    q1.put(indata.copy())

def callback2(indata, frames, time_info, status):
    if status:
        print("Device 2:", status)
    q2.put(indata.copy())

# -----------------------------
# Recording threads
# -----------------------------
def record_stream(device, q, frames_list):
    with sd.InputStream(samplerate=samplerate, device=device, channels=1,
                        callback=lambda indata, frames, time_info, status: q.put(indata.copy())):
        start_time = time.time()
        while time.time() - start_time < duration:
            frames_list.append(q.get())

# -----------------------------
# Main
# -----------------------------
frames1 = []
frames2 = []

t1 = threading.Thread(target=record_stream, args=(device1, q1, frames1))
t2 = threading.Thread(target=record_stream, args=(device2, q2, frames2))

print("Recording both devices...")
t1.start()
t2.start()

t1.join()
t2.join()
print("Recording finished. Combining into one WAV file...")

# -----------------------------
# Combine into one stereo WAV (device1 = left, device2 = right)
# -----------------------------
# Convert list of arrays to single array
data1 = np.concatenate(frames1, axis=0)
data2 = np.concatenate(frames2, axis=0)

# Pad the shorter array if needed
min_len = min(len(data1), len(data2))
data1 = data1[:min_len]
data2 = data2[:min_len]

# Stack as two channels
stereo_data = np.column_stack((data1, data2))

# Write WAV
sf.write(file_out, stereo_data, samplerate)
print("Saved dual-track WAV as:", file_out)
