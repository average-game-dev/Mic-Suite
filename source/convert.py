import subprocess as sub
import threading
import os
import sys

input_dir = sys.argv[1]
if not os.path.isdir(input_dir):
    print("[ERROR] What the fuck bro, that doesn't exist?")
    exit(1)
output_dir = os.path.join(input_dir, "output")

# Make sure output dir exists
os.makedirs(output_dir, exist_ok=True)

# Get input files, excluding "output" folder
files = [os.path.join(input_dir, f) for f in os.listdir(input_dir) if f != "output"]

# Clear old output files
for file in os.listdir(output_dir):
    os.remove(os.path.join(output_dir, file))

# Supported extensions (with dots)
audio_exts = {
    ".mp3", ".aac", ".m4a", ".wma", ".ogg", ".opus", ".mp2", ".ra", ".rm", ".flac",
    ".alac", ".wav", ".aiff", ".aif", ".wv", ".tta", ".pcm", ".caf", ".snd", ".au",
    ".voc", ".dsf", ".dff", ".mod", ".xm", ".it", ".s3m"
}

def worker(file: str):
    _, ext = os.path.splitext(file)
    ext = ext.lower()
    if ext not in audio_exts:
        print(f"[INFO] File {file} isn't an audio file, skipping.")
        return

    out_name = os.path.splitext(os.path.basename(file))[0] + ".wav"
    out_path = os.path.join(output_dir, out_name)

    print(f"[INFO] Converting {file} -> {out_path}")
    sub.run(["ffmpeg", "-y", "-i", file, out_path], stdout=sub.DEVNULL, stderr=sub.DEVNULL)

workers = []
for f in files:
    t = threading.Thread(target=worker, args=(f,))
    workers.append(t)
    t.start()

for t in workers:
    t.join()

print(f"[INFO] Conversion Finished. Check {output_dir} for the converted files.")
