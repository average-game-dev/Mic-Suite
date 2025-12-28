import io
import keyboard
import sounddevice as sd
import numpy as np
import speech_recognition as sr
import wave
import comtypes.client
from multiprocessing import Process

# im not rewriting this for linux, if you want to you can and submit a pull request

# ------------------- CONFIG -------------------
SAMPLE_RATE = 16000
CHANNELS = 1
KEY = '`'  # hold to speak
POST_RELEASE_SECONDS = 0.25  # record extra after release

# ------------------- OUTPUT DEVICE SELECTION -------------------

def choose_output_devices():
    print("=== Output Devices ===")
    devs = sd.query_devices()
    output_devs = [d for d in devs if d['max_output_channels'] > 0]

    for idx, d in enumerate(output_devs):
        print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) "
              f"(I/O: {d['max_input_channels']}/{d['max_output_channels']})")

    try:
        d1_idx = int(input("Primary output device index: ").strip())
        d2_idx = int(input("Secondary output device index (loopback/mic): ").strip())

        d1_name = output_devs[d1_idx]['name']
        d2_name = output_devs[d2_idx]['name']
        return d1_name, d2_name
    except (ValueError, IndexError):
        print("Invalid device selection.")
        exit(1)

# ------------------- DEVICE RESOLUTION -------------------

def find_output_device(name_substring):
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev.get("max_output_channels", 0) > 0:
            if name_substring.lower() in dev["name"].lower():
                return idx
    raise RuntimeError(f"Output device not found: {name_substring}")

def get_device_ids():
    d1 = find_output_device(DEVICE_1_NAME)
    d2 = find_output_device(DEVICE_2_NAME)
    return d1, d2

# ------------------- STT -------------------

recognizer = sr.Recognizer()

def record_while_held(key=KEY, post_release=POST_RELEASE_SECONDS):
    frames = []

    def callback(indata, frames_count, time, status):
        if status:
            print(status)
        frames.append(indata.copy())

    print(f"Holding `{key}` to record...")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=callback):
        while keyboard.is_pressed(key):
            sd.sleep(20)

        extra_frames = int(post_release * SAMPLE_RATE)
        print(f"Recording extra {post_release} seconds...")
        extra_data = sd.rec(extra_frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32')
        sd.wait()
        frames.append(extra_data)

    if not frames:
        return None
    return np.concatenate(frames, axis=0)

def audio_to_file_like(audio):
    buf = io.BytesIO()
    audio_int16 = (audio * 32767).astype(np.int16)

    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

    buf.seek(0)
    return buf

# ------------------- TTS -------------------

def tts_to_audio(text, voice):
    stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
    fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")

    fmt.Type = 22  # 22 kHz 16-bit mono PCM
    stream.Format = fmt
    voice.AudioOutputStream = stream

    voice.Speak(text)

    audio_bytes = bytes(stream.GetData())
    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return audio

def play_device(audio, samplerate, device_id):
    sd.play(audio, samplerate=samplerate, device=device_id)
    sd.wait()

def select_voice():
    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    voices = voice.GetVoices()

    print("Available voices:")
    for i in range(voices.Count):
        print(f"{i}: {voices.Item(i).GetDescription()}")

    while True:
        try:
            choice = int(input("Select voice index: "))
            if 0 <= choice < voices.Count:
                voice.Voice = voices.Item(choice)
                print(f"Selected voice: {voice.Voice.GetDescription()}")
                return voice
            else:
                print("Invalid index, try again.")
        except ValueError:
            print("Enter a valid number.")

# ------------------- MAIN LOOP -------------------

def main():
    global DEVICE_1_NAME, DEVICE_2_NAME

    # ✅ FIX: Device selection happens ONLY ONCE now
    DEVICE_1_NAME, DEVICE_2_NAME = choose_output_devices()

    selected_voice = select_voice()
    selected_voice.Rate = 0
    selected_voice.Volume = 100

    print("\nHold ` to speak. Ctrl+C to quit.")
    try:
        while True:
            keyboard.wait(KEY)
            audio = record_while_held(KEY)
            if audio is None or len(audio) < 1000:
                print("Recording too short, try again.")
                continue

            file_like = audio_to_file_like(audio)
            with sr.AudioFile(file_like) as source:
                data = recognizer.record(source)

                try:
                    text = recognizer.recognize_google(data)
                    print(">>", text)

                    speech_audio = tts_to_audio(text, selected_voice)

                    d1, d2 = get_device_ids()

                    p1 = Process(target=play_device, args=(speech_audio, 22050, d1))
                    p2 = Process(target=play_device, args=(speech_audio, 22050, d2))
                    p1.start()
                    p2.start()
                    p1.join()
                    p2.join()

                except sr.UnknownValueError:
                    print(">> [Could not understand audio]")
                except sr.RequestError as e:
                    print(f">> [Request failed; {e}]")

    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
