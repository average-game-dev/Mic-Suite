import os
import json
import re
import subprocess
import random
import numpy as np
import sounddevice as sd
import soundfile as sf
import comtypes.client
import tempfile

def greedy_phrase_match(words, word_sounds, max_phrase_len=5, reject_chance=0.1):
    buffers = []
    i = 0

    while i < len(words):

        candidates = []

        # collect ALL possible phrase matches
        for size in range(1, max_phrase_len + 1):
            if i + size > len(words):
                continue

            phrase = " ".join(words[i:i+size])

            if phrase in word_sounds and word_sounds[phrase]:
                candidates.append((size, phrase))

        # sort by longest first (true greedy order)
        candidates.sort(reverse=True, key=lambda x: x[0])

        chosen = None

        # try candidates in order, but allow rejection
        for size, phrase in candidates:
            if random.random() < reject_chance:
                continue  # reject and try next-best

            chosen = (size, phrase)
            break

        if chosen:
            size, phrase = chosen
            audio = random.choice(word_sounds[phrase])
            buffers.append(("audio", audio))
            i += size
        else:
            # total failure fallback
            buffers.append(("tts", words[i]))
            i += 1

    return buffers
def apply_edge_fade(data, fade_samples=128):
    """
    Applies a very short fade-in and fade-out to avoid hard edges.
    Does NOT overlap clips, so words stay distinct.
    """
    if len(data) < fade_samples * 2:
        return data  # too short to safely fade

    fade_in = np.linspace(0.0, 1.0, fade_samples)[:, None]
    fade_out = np.linspace(1.0, 0.0, fade_samples)[:, None]

    data[:fade_samples] *= fade_in
    data[-fade_samples:] *= fade_out

    return data

print("=== Output Devices ===")
devs = sd.query_devices()
for idx, d in enumerate(devs):
    if d['max_output_channels'] > 0:
        print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) "
                f"(I/O: {d['max_input_channels']}/{d['max_output_channels']})")
try:
    dev1 = int(input("Primary output device ID: ").strip())
except ValueError:
    print("Invalid device ID.")
    exit(1)

stream = None

def init_audio():
    global stream

    stream = sd.OutputStream(
        samplerate=stream_sr,
        channels=2,
        dtype='float32',
        device=dev1,
        blocksize=1024
    )
    stream.start()

def resample_audio(data, orig_sr, target_sr):
    if orig_sr == target_sr:
        return data

    duration = data.shape[0] / orig_sr
    target_length = int(duration * target_sr)

    old_indices = np.linspace(0, 1, num=data.shape[0])
    new_indices = np.linspace(0, 1, num=target_length)

    resampled = np.zeros((target_length, data.shape[1]), dtype=np.float32)

    for ch in range(data.shape[1]):
        resampled[:, ch] = np.interp(new_indices, old_indices, data[:, ch])

    return resampled

def trim_silence(data, threshold=0.01, min_silence_samples=400, pad_samples=10000):
    """
    Removes leading and trailing silence from stereo audio.
    threshold: amplitude below which is considered silence
    min_silence_samples: avoids trimming tiny dips inside speech
    """
    # Convert to mono energy for detection
    mono = np.max(np.abs(data), axis=1)

    # Find indices above threshold
    indices = np.where(mono > threshold)[0]

    if len(indices) == 0:
        return data  # all silence, don't break it

    start = indices[0]
    end = indices[-1]

    # Small padding so it doesn't sound cut off
    pad = min_silence_samples + pad_samples
    start = max(0, start - pad)
    end = min(len(data), end + pad)

    return data[start:end]

# ---------------- CONFIG ----------------
JSON_PATH = "word.json"
SOUND_DIR = "./words"
CACHE_DIR = "cache"
stream_sr = 48000
WORD_GAP_SECONDS = 0.01
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

    data = apply_edge_fade(data, fade_samples=128)
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
def tts_to_audio(text):
    # Create temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_path = tmp.name
    tmp.close()

    # Initialize SAPI
    engine = comtypes.client.CreateObject("SAPI.SpVoice")
    stream = comtypes.client.CreateObject("SAPI.SpFileStream")

    # 3 = SSFMCreateForWrite
    stream.Open(tmp_path, 3)
    engine.AudioOutputStream = stream

    engine.Speak(text)

    stream.Close()

    # Load into numpy
    data, sr = sf.read(tmp_path, dtype="float32")

    if data.ndim == 1:
        data = np.column_stack([data, data])

    if sr != stream_sr:
        print(f"[TTS] Resampling {sr} Hz -> {stream_sr} Hz")
        data = resample_audio(data, sr, stream_sr)

    data = trim_silence(data)

    data = apply_edge_fade(data, fade_samples=128)
    return data

# ---------- SENTENCE BUILDER ----------

def clean_word(word: str):
    return re.sub(r"[^\w']", "", word.lower())

def build_sentence_audio(sentence: str):
    words = sentence.lower().split()
    #words = [clean_word(w) for w in sentence.lower().split()]
    #schedule = greedy_phrase_match(
    #    words,
    #    AUDIO_CACHE,
    #    max_phrase_len=4,
    #    reject_chance=0.08
    #)
    #return schedule
    buffers = []
    tts_buffer = []

    gap_samples = int(stream_sr * WORD_GAP_SECONDS)
    gap = np.zeros((gap_samples, 2), dtype=np.float32)

    for raw in words:
        word = clean_word(raw)

        if word in AUDIO_CACHE and AUDIO_CACHE[word]:
            # store pending TTS in case caller wants it
            if tts_buffer:
                # keep TTS order in a single fallback string
                buffers.append(("tts", " ".join(tts_buffer)))
                tts_buffer.clear()

            audio_variant = random.choice(AUDIO_CACHE[word])
            print(f"[Sentence] using cached {word} ({audio_variant.shape[0]} samples)")
            buffers.append(("audio", audio_variant))
            if gap_samples > 0:
                buffers.append(("audio", gap.copy()))
        else:
            print(f"[Sentence] fallback TTS for '{raw}'")
            tts_buffer.append(raw)

    if tts_buffer:
        buffers.append(("tts", " ".join(tts_buffer)))

    if not buffers:
        return []

    return buffers

def play_sentence_audio_and_tts(sentence: str):
    schedule = build_sentence_audio(sentence)

    final_buffers = []

    for kind, payload in schedule:
        if kind == "audio":
            if payload.shape[0] > 0:
                final_buffers.append(payload)

        elif kind == "tts":
            print(f"[TTS GEN] {payload}")
            tts_audio = tts_to_audio(payload)
            final_buffers.append(tts_audio)

    if not final_buffers:
        return

    full_audio = np.concatenate(final_buffers, axis=0)
    tail_samples = int(stream_sr * 0.15)
    tail = np.zeros((tail_samples, 2), dtype=np.float32)
    full_audio = np.concatenate([full_audio, tail], axis=0)

    stream.write(full_audio)
    sd.wait()


# ---------- CLI ----------

def main():
    init_audio()
    print("Hybrid Cached Word Speaker (Random Variants)")
    print("Type sentence. 'exit' to quit.\n")

    while True:
        try:
            text = input("> ").strip()
            if text.lower() in {"exit", "quit"}:
                break

            if text:
                play_sentence_audio_and_tts(text)

        except KeyboardInterrupt:
            break

    print("Goodbye.")

if __name__ == "__main__":
    main()