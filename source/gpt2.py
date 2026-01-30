import pyttsx3
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import sounddevice as sd
import soundfile as sf
import tempfile
import os
import threading

# im not rewriting this for linux, if you want to you can and submit a pull request

def choose_output_devices():
    print("=== Output Devices ===")
    devs = sd.query_devices()
    for idx, d in enumerate(devs):
        if d['max_output_channels'] > 0:
            print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")
    try:
        d1 = int(input("Primary output device ID: ").strip())
        d2 = int(input("Secondary output device ID (loopback/mic): ").strip())
        return d1, d2
    except ValueError:
        print("Invalid device ID.")
        exit(1)

device_ids = choose_output_devices()

max_length = 80
temperature = 2.0
voice_rate = 150

# GPT-2
tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
model = GPT2LMHeadModel.from_pretrained("gpt2")
model.eval()

def generate_text(prompt):
    inputs = tokenizer(prompt, return_tensors="pt")
    outputs = model.generate(
        **inputs, max_length=max_length,
        do_sample=True, temperature=temperature
    )
    return ''.join(c for c in tokenizer.decode(outputs[0], skip_special_tokens=True) 
                   if 32 <= ord(c) <= 126 or c in '\n.,!?')  # clean text

def play_on_device(filename, device_id):
    data, fs = sf.read(filename, dtype='float32')
    sd.play(data, fs, device=device_id)
    sd.wait()

def speak_dual(text, device_ids=device_ids):
    # Create a fresh engine for each prompt
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    engine.setProperty("voice", voices[0].id)
    engine.setProperty("rate", voice_rate)

    tmp_file = tempfile.mktemp(suffix=".wav")
    engine.save_to_file(text, tmp_file)
    engine.runAndWait()
    engine.stop()  # stop the engine so it can be recreated next loop

    threads = []
    for dev_id in device_ids:
        t = threading.Thread(target=play_on_device, args=(tmp_file, dev_id))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    os.remove(tmp_file)

# CLI loop
print("=== GPT-2 CLI CHAOS (CTRL+C to exit) ===")
while True:
    try:
        prompt = input(">> ")
        if not prompt.strip():
            continue
        text = generate_text(prompt)
        print(f"\n--- GPT-2 OUTPUT ---\n{text}\n")
        speak_dual(text, device_ids=[7,11])
    except KeyboardInterrupt:
        print("\nExiting GPT-2 CLI. Bye!")
        break
