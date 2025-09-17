import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import time

# --------------------------
# Settings
# --------------------------
music_folder = r"songs1"  # folder containing your songs
target_sr = 48000                  # target sample rate
skip_if_exists = True              # skip files already normalized

# --------------------------
# Function to process one file
# --------------------------
def process_song(file):
    base, ext = os.path.splitext(file)
    output_file = f"{base}_{target_sr}hz_normalized.wav"

    if skip_if_exists and os.path.exists(output_file):
        return "skip", output_file, 0.0

    temp_resampled = output_file.replace("_normalized.wav", "_resampled.wav")
    song_start = time.time()

    try:
        # Step 1: Resample
        subprocess.run([
            "ffmpeg", "-y", "-i", file,
            "-ar", str(target_sr), "-ac", "2", "-c:a", "pcm_f32le", temp_resampled
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Step 2: Loudness normalize
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_resampled,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", str(target_sr), "-ac", "2", "-c:a", "pcm_f32le", output_file
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        os.remove(temp_resampled)
        song_end = time.time()
        duration = song_end - song_start
        return "done", output_file, duration
    except subprocess.CalledProcessError:
        song_end = time.time()
        duration = song_end - song_start
        return "error", file, duration

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    files = [os.path.join(music_folder, f) for f in os.listdir(music_folder)
             if f.lower().endswith(('.mp3', '.wav', '.flac', '.m4a'))]

    if not files:
        print("No audio files found in folder.")
        exit(1)

    total_files = len(files)
    processed_count = 0
    overall_start = time.time()

    print(f"=== Preprocessing {total_files} songs using {multiprocessing.cpu_count()} CPU cores ===")
    print(f"Start time: {time.strftime('%H:%M:%S', time.localtime(overall_start))}\n")

    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        futures = {executor.submit(process_song, f): f for f in files}
        for future in as_completed(futures):
            status, fname, duration = future.result()
            processed_count += 1

            elapsed = time.time() - overall_start
            avg_time = elapsed / processed_count
            remaining = avg_time * (total_files - processed_count)

            if status == "done":
                print(f"[{processed_count}/{total_files}] DONE: {os.path.basename(fname)} | "
                      f"Time: {int(duration)}s | ETA: {int(remaining)}s")
            elif status == "skip":
                print(f"[{processed_count}/{total_files}] SKIP: {os.path.basename(fname)} | ETA: {int(remaining)}s")
            else:
                print(f"[{processed_count}/{total_files}] ERROR: {os.path.basename(fname)} | Time: {int(duration)}s | ETA: {int(remaining)}s")

    overall_end = time.time()
    print(f"\nAll songs processed!")
    print(f"End time: {time.strftime('%H:%M:%S', time.localtime(overall_end))}")
    print(f"Total elapsed time: {int(overall_end - overall_start)} seconds")
