import os
import json
import re
import subprocess
import random
import numpy as np
import sounddevice as sd
import soundfile as sf
import pyttsx3

# ---------------- CONFIG ----------------
JSON_PATH = "word.json"
SOUND_DIR = "./words"
CACHE_DIR = "cache"
stream_sr = 48000
WORD_GAP_SECONDS = 0.08
NORMALIZE = True
# ----------------------------------------

# ---------- AUDIO CACHE SYSTEM ----------

def load_audio_cached(file, normalize=True, recurse=False):
    base_name = os.path.splitext(os.path.basename(file))[0]

    cache_path = os.path.join(SOUND_DIR, CACHE_DIR)
    os.makedirs(cache_path, exist_ok=True)

    norm_tag = "norm" if normalize else "raw"
    cached_file = os.path.join(
        cache_path,
        f"{base_name}_{stream_sr}hz_{norm_tag}.flac"
    )

    if not os.path.exists(cached_file):
        cmd = [
            "ffmpeg", "-y",
            "-i", file,
            "-ar", str(stream_sr),
            "-ac", "2"
        ]

        if normalize:
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]

        cmd += ["-c:a", "flac", cached_file]

        print(f"[Cache MISS] Creating {cached_file}")
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        print(f"[Cache HIT] {cached_file}")

    try:
        data, sr = sf.read(cached_file, dtype="float32")
    except RuntimeError:
        if not recurse:
            print("[Cache Corrupt] Rebuilding...")
            os.remove(cached_file)
            return load_audio_cached(file, normalize, True)
        else:
            raise

    if data.ndim == 1:
        data = np.column_stack([data, data])

    if sr != stream_sr:
        raise RuntimeError(f"Sample rate mismatch: {sr} Hz")

    return data


# ---------- LOAD WORD MAP ----------

with open(JSON_PATH, "r", encoding="utf-8") as f:
    raw_map = json.load(f)

WORD_SOUNDS = {}

for word, value in raw_map.items():
    word = word.lower()
    if isinstance(value, list):
        WORD_SOUNDS[word] = value
    else:
        WORD_SOUNDS[word] = [value]  # normalize to list

AUDIO_CACHE = {}

def preload_sounds():
    for word, file_list in WORD_SOUNDS.items():
        AUDIO_CACHE[word] = []
        for path in file_list:
            if os.path.exists(path):
                try:
                    audio = load_audio_cached(path, NORMALIZE)
                    AUDIO_CACHE[word].append(audio)
                except Exception as e:
                    print(f"[Preload error] {path}: {e}")

preload_sounds()

# ---------- TTS ----------

tts = pyttsx3.init()
tts.setProperty("rate", 180)

def speak_tts(text):
    tts.say(text)
    tts.runAndWait()

# ---------- SENTENCE BUILDER ----------

def clean_word(word: str):
    return re.sub(r"[^\w']", "", word.lower())

def build_sentence_audio(sentence: str):
    words = sentence.split()
    buffers = []
    tts_buffer = []

    gap_samples = int(stream_sr * WORD_GAP_SECONDS)
    gap = np.zeros((gap_samples, 2), dtype=np.float32)

    for raw in words:
        word = clean_word(raw)

        if word in AUDIO_CACHE and AUDIO_CACHE[word]:
            if tts_buffer:
                speak_tts(" ".join(tts_buffer))
                tts_buffer.clear()

            # 🔥 Randomly select variant
            audio_variant = random.choice(AUDIO_CACHE[word])
            buffers.append(audio_variant)
            buffers.append(gap.copy())
        else:
            tts_buffer.append(raw)

    if tts_buffer:
        speak_tts(" ".join(tts_buffer))

    if not buffers:
        return None

    buffers = buffers[:-1]  # remove trailing gap
    return np.concatenate(buffers, axis=0)


# ---------- CLI ----------

def main():
    print("Hybrid Cached Word Speaker (Random Variants)")
    print("Type sentence. 'exit' to quit.\n")

    while True:
        try:
            text = input("> ").strip()
            if text.lower() in {"exit", "quit"}:
                break

            if text:
                audio = build_sentence_audio(text)
                if audio is not None:
                    sd.play(audio, stream_sr)
                    sd.wait()

        except KeyboardInterrupt:
            break

    print("Goodbye.")

if __name__ == "__main__":
    main()