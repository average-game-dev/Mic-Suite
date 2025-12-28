import comtypes.client
import sounddevice as sd
import numpy as np
import threading

# im not rewriting this for linux, if you want to you can and submit a pull request

SAMPLE_RATE = 22050  # matches SAPI SpAudioFormat type 22


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


DEVICE_1_NAME, DEVICE_2_NAME = choose_output_devices()


def find_output_device(name_substring):
    """Search for an audio output device containing the given substring."""
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev.get("max_output_channels", 0) > 0 and name_substring.lower() in dev["name"].lower():
            return idx
    raise RuntimeError(f"Output device not found: {name_substring}")


def get_device_ids():
    """Find both devices dynamically each time."""
    return find_output_device(DEVICE_1_NAME), find_output_device(DEVICE_2_NAME)


def play_device(audio, samplerate, device_id):
    """Plays audio to the specified output device."""
    try:
        sd.play(audio, samplerate=samplerate, device=device_id)
        sd.wait()
    except Exception as e:
        print(f"Error playing on device {device_id}: {e}")


def tts_to_audio(text, voice):
    """Convert text to PCM audio using SAPI memory stream."""
    stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
    fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
    fmt.Type = 22  # 22 kHz 16-bit mono PCM
    stream.Format = fmt
    voice.AudioOutputStream = stream

    voice.Speak(text)

    audio_tuple = stream.GetData()  # returns tuple of ints
    audio_bytes = bytes(audio_tuple)  # convert tuple -> bytes
    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def select_voice():
    """Let user pick a SAPI voice."""
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
                print(f"Selected: {voice.Voice.GetDescription()}")
                return voice
            else:
                print("Invalid index.")
        except ValueError:
            print("Enter a number.")


def main():
    selected_voice = select_voice()
    selected_voice.Rate = 0
    selected_voice.Volume = 100

    print("\nType text to speak. Ctrl+C to quit.")

    while True:
        try:
            text = input("> ").strip()
            if not text:
                continue

            audio = tts_to_audio(text, selected_voice)
            device1_id, device2_id = get_device_ids()

            t1 = threading.Thread(target=play_device, args=(audio, SAMPLE_RATE, device1_id))
            t2 = threading.Thread(target=play_device, args=(audio, SAMPLE_RATE, device2_id))

            t1.start()
            t2.start()

            t1.join()
            t2.join()

        except KeyboardInterrupt:
            print("\nExiting...")
            break


if __name__ == "__main__":
    main()
