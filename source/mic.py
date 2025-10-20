import sounddevice as sd
import numpy as np
import queue
import scipy.signal
import ctypes
import os
import threading
import sys

def scroll_lock_on():
    # Windows virtual key for Caps Lock is 0x14
    # GetKeyState returns low bit = toggle state
    return bool(ctypes.WinDLL("User32.dll").GetKeyState(0x91) & 1)


# ---------------- MIC / QUEUE ----------------
MIC_GAIN = 1.5  # base mic amplification
mic_queue = queue.Queue()
effects = []

# ---------------- BASE EFFECTS ----------------
class Effect:
    def process(self, chunk: np.ndarray) -> np.ndarray:
        return chunk

class GainEffect(Effect):
    def __init__(self, gain=1.0):
        self.gain = gain
    def process(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32) * self.gain
        np.clip(chunk, -1.0, 1.0, out=chunk)
        return chunk

class HypercamMicEffect(Effect):
    def __init__(self, samplerate=48000):
        self.sos = scipy.signal.butter(4, [150, 4000], btype='bandpass', fs=samplerate, output='sos')
        self.decim = int(samplerate // 8000)
        self.gain = 1.0
        self.noise_level = 1e-4
        self.threshold = 0.15
    def process(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32)
        if chunk.ndim == 1: chunk = chunk.reshape(-1,1)
        de_noised = chunk.copy()
        de_noised[np.abs(de_noised) < self.threshold] = 0.0
        filtered = scipy.signal.sosfilt(self.sos, de_noised[:,0])
        decimated = filtered[::self.decim]
        upsampled = np.repeat(decimated, self.decim)[:len(filtered)]
        amplified = upsampled * self.gain
        crushed = np.round(amplified * 128) / 128.0
        noise = np.random.normal(0, self.noise_level, size=crushed.shape)
        out = crushed + noise
        out = np.clip(out, -1.0, 1.0)
        return out.astype(np.float32).reshape(-1,1)

# ---------------- PREBAKED VOICE EFFECTS ----------------
class RobotVoiceEffect(Effect):
    def __init__(self, freq=30, samplerate=48000):
        self.freq = freq
        self.samplerate = samplerate
        self.phase = 0
    def process(self, chunk):
        chunk = chunk.flatten()
        t = np.arange(len(chunk)) / self.samplerate
        carrier = np.sign(np.sin(2*np.pi*self.freq*t + self.phase))
        out = chunk * carrier
        self.phase += 2*np.pi*self.freq*len(chunk)/self.samplerate
        return out.reshape(-1,1)

class TelephoneEffect(Effect):
    def __init__(self, samplerate=48000):
        self.sos = scipy.signal.butter(4,[300,3400],btype='bandpass',fs=samplerate,output='sos')
    def process(self, chunk):
        return scipy.signal.sosfilt(self.sos, chunk.flatten()).reshape(-1,1)

class LoFiEffect(Effect):
    def __init__(self,bits=6,samplerate=48000,target_rate=8000):
        self.bits=bits
        self.decim=int(samplerate/target_rate)
    def process(self, chunk):
        flat=chunk.flatten()[::self.decim]
        flat=np.round(flat*(2**self.bits))/(2**self.bits)
        return np.repeat(flat,self.decim)[:len(chunk)].reshape(-1,1)

class MegaphoneEffect(Effect):
    def __init__(self,samplerate=48000):
        self.sos=scipy.signal.butter(2,[500,3000],btype='bandpass',fs=samplerate,output='sos')
    def process(self,chunk):
        return scipy.signal.sosfilt(self.sos,chunk.flatten()).reshape(-1,1)

class WhisperEffect(Effect):
    def __init__(self,noise_level=0.002):
        self.noise_level=noise_level
    def process(self,chunk):
        chunk = chunk.flatten()*0.3
        noise = np.random.normal(0,self.noise_level,size=len(chunk))
        return (chunk+noise).reshape(-1,1)

class AlienEffect(Effect):
    def __init__(self,freq=60,pitch_up=1.2,samplerate=48000):
        self.freq=freq
        self.pitch_up=pitch_up
        self.samplerate=samplerate
        self.phase=0
    def process(self,chunk):
        flat=np.interp(np.linspace(0,len(chunk)-1,int(len(chunk)*self.pitch_up)),
                       np.arange(len(chunk)),chunk.flatten())
        t=np.arange(len(flat))/self.samplerate
        carrier=np.sin(2*np.pi*self.freq*t+self.phase)
        self.phase+=2*np.pi*self.freq*len(flat)/self.samplerate
        return (flat*carrier).reshape(-1,1)

# ---------------- NEW 10 BASE EFFECTS ----------------
class EchoEffect(Effect):
    def __init__(self, delay=0.3, decay=0.5, samplerate=48000):
        self.delay_samples = int(delay*samplerate)
        self.buffer = np.zeros(self.delay_samples)
        self.decay = decay
    def process(self, chunk):
        out = chunk.flatten().copy()
        for i in range(len(out)):
            echo_val = self.buffer[i % self.delay_samples]
            self.buffer[i % self.delay_samples] = out[i] + echo_val*self.decay
            out[i] += echo_val
        return np.clip(out, -1, 1).reshape(-1,1)

class ReverbEffect(Effect):
    def __init__(self, decay=0.3):
        self.decay = decay
        self.prev = 0
    def process(self, chunk):
        out = []
        for x in chunk.flatten():
            self.prev = self.prev*self.decay + x
            out.append(self.prev)
        return np.clip(out, -1, 1).reshape(-1,1)

class DistortionEffect(Effect):
    def __init__(self, gain=5.0, threshold=0.5):
        self.gain=gain
        self.threshold=threshold
    def process(self, chunk):
        out=chunk.flatten()*self.gain
        out=np.clip(out,-self.threshold,self.threshold)
        return (out/self.threshold).reshape(-1,1)

class FlangerEffect(Effect):
    def __init__(self, depth=0.002, rate=0.25, samplerate=48000):
        self.depth=int(depth*samplerate)
        self.rate=rate
        self.samplerate=samplerate
        self.phase=0
        self.buffer=np.zeros(samplerate)
        self.idx=0
    def process(self, chunk):
        out=np.zeros_like(chunk.flatten())
        for i,x in enumerate(chunk.flatten()):
            delay=int((np.sin(2*np.pi*self.phase)*0.5+0.5)*self.depth)
            self.phase+=self.rate/self.samplerate
            self.buffer[self.idx]=x
            out[i]=x+0.7*self.buffer[(self.idx-delay)%len(self.buffer)]
            self.idx=(self.idx+1)%len(self.buffer)
        return np.clip(out,-1,1).reshape(-1,1)

class ChorusEffect(Effect):
    def __init__(self, depth=0.003, rate=1.5, samplerate=48000):
        self.depth=int(depth*samplerate)
        self.rate=rate
        self.samplerate=samplerate
        self.phase=0
        self.buffer=np.zeros(samplerate)
        self.idx=0
    def process(self, chunk):
        out=np.zeros_like(chunk.flatten())
        for i,x in enumerate(chunk.flatten()):
            delay=int((np.sin(2*np.pi*self.phase)*0.5+0.5)*self.depth)
            self.phase+=self.rate/self.samplerate
            self.buffer[self.idx]=x
            out[i]=0.5*x+0.5*self.buffer[(self.idx-delay)%len(self.buffer)]
            self.idx=(self.idx+1)%len(self.buffer)
        return np.clip(out,-1,1).reshape(-1,1)

class TremoloEffect(Effect):
    def __init__(self, freq=5.0, samplerate=48000):
        self.freq=freq
        self.samplerate=samplerate
        self.phase=0
    def process(self, chunk):
        t=np.arange(len(chunk))/self.samplerate
        lfo=0.5*(1+np.sin(2*np.pi*self.freq*t+self.phase))
        self.phase+=2*np.pi*self.freq*len(chunk)/self.samplerate
        return (chunk.flatten()*lfo).reshape(-1,1)

class VibratoEffect(Effect):
    def __init__(self, depth=0.002, rate=5.0, samplerate=48000):
        self.depth=depth
        self.rate=rate
        self.samplerate=samplerate
        self.phase=0
    def process(self, chunk):
        t=np.arange(len(chunk))
        delay=self.depth*np.sin(2*np.pi*self.rate*t/self.samplerate+self.phase)
        idx=t+delay*self.samplerate
        idx=np.clip(idx,0,len(chunk)-1)
        out=np.interp(idx,t,chunk.flatten())
        return out.reshape(-1,1)

class OverdriveEffect(Effect):
    def __init__(self, drive=2.0):
        self.drive=drive
    def process(self, chunk):
        out=np.tanh(chunk.flatten()*self.drive)
        return out.reshape(-1,1)

class BitcrusherEffect(Effect):
    def __init__(self, bits=4):
        self.levels=2**bits
    def process(self, chunk):
        flat=chunk.flatten()
        out=np.round(flat*self.levels)/self.levels
        return out.reshape(-1,1)

class HighPassEffect(Effect):
    def __init__(self, cutoff=1000, samplerate=48000):
        self.sos=scipy.signal.butter(4,cutoff,btype='highpass',fs=samplerate,output='sos')
    def process(self,chunk):
        return scipy.signal.sosfilt(self.sos,chunk.flatten()).reshape(-1,1)

# ---------------*- AUDIO STREAM ----------------
last_chunk=None
def mic_callback(indata, frames, time, status):
    if status: print(status)
    mic_queue.put(indata.copy()*MIC_GAIN)

def out_callback(outdata, frames, time, status):
    global last_chunk
    try:
        chunk = mic_queue.get_nowait()
        last_chunk = chunk
    except queue.Empty:
        chunk = last_chunk if last_chunk is not None else np.zeros((frames, 1), dtype='float32')

    if not scroll_lock_on():  # only process if Caps Lock is OFF
        for effect in effects:
            chunk = effect.process(chunk)
    else:
        # mute if Caps Lock is on
        chunk = np.zeros((frames, 1), dtype='float32')

    if chunk.shape[0] < frames:
        chunk = np.pad(chunk, ((0, frames - chunk.shape[0]), (0, 0)))
    elif chunk.shape[0] > frames:
        chunk = np.interp(np.linspace(0, len(chunk)-1, frames),
                          np.arange(len(chunk)), chunk.flatten()).reshape(-1,1)

    outdata[:] = chunk


# ---------------- EFFECT REGISTRY ----------------
effect_classes={
    'gain':GainEffect,'hypercam':HypercamMicEffect,'robot':RobotVoiceEffect,'telephone':TelephoneEffect,
    'lofi':LoFiEffect,'megaphone':MegaphoneEffect,'whisper':WhisperEffect,'alien':AlienEffect,
    'echo':EchoEffect,'reverb':ReverbEffect,'distortion':DistortionEffect,'flanger':FlangerEffect,
    'chorus':ChorusEffect,'tremolo':TremoloEffect,'vibrato':VibratoEffect,'overdrive':OverdriveEffect,
    'bitcrusher':BitcrusherEffect,'highpass':HighPassEffect
}

# ---------------- MAIN ----------------
print("=== Devices ===")
for idx,d in enumerate(sd.query_devices()):
    print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}")

mic_id=int(input("Enter your mic device ID: "))
out_id=int(input("Enter output device ID: "))

samplerate=48000
blocksize=1024

with sd.InputStream(samplerate=samplerate,device=mic_id,channels=1,
                    blocksize=blocksize,callback=mic_callback):
    with sd.OutputStream(samplerate=samplerate,device=out_id,channels=1,
                         blocksize=blocksize,callback=out_callback):
        print("Streaming mic. Type commands (Ctrl+C to exit).")
        print("Commands: effect add <name>, effect remove <index|name>, effect list, help")
        try:
            while True:
                cmd=input("> ").strip().lower()
                if cmd.startswith("effect add"):
                    name = cmd.split()[2]
                    if name == "all":
                        effects = []
                        for cls_name, cls in effect_classes.items():
                            if 'samplerate' in cls.__init__.__code__.co_varnames:
                                effects.append(cls(samplerate=samplerate))
                            else:
                                effects.append(cls())
                        print("Added all effects.")
                    else:
                        cls = effect_classes.get(name)
                        if cls:
                            if name == 'hypercam':
                                effects = [e for e in effects if not isinstance(e, HypercamMicEffect)]
                            effects.append(cls(samplerate=samplerate) if 'samplerate' in cls.__init__.__code__.co_varnames else cls())
                            print(f"Added effect: {name}")
                        else:
                            print(f"No such effect: {name}")

                elif cmd.startswith("effect remove"):
                    key = cmd.split()[2]
                    if key == "all":
                        effects = []
                        print("Removed all effects.")
                    else:
                        try:
                            if key.isdigit():
                                removed = effects.pop(int(key))
                            else:
                                for i,e in enumerate(effects):
                                    if e.__class__.__name__.lower().startswith(key):
                                        removed = effects.pop(i)
                                        break
                                else:
                                    raise ValueError(f"No effect named '{key}'")
                            print(f"Removed effect: {removed.__class__.__name__}")
                        except Exception as e:
                            print("Invalid remove:", e)

                elif cmd=="effect list":
                    for i,e in enumerate(effects):
                        print(f"[{i}] {e.__class__.__name__}")
                elif cmd=="effect list all":
                    for effect in effect_classes:
                        print(f"; {effect}")
                elif cmd.split()[0] =="gain":
                    MIC_GAIN = float(cmd.split()[1])
                elif cmd=="help":
                    print("Commands: effect add <name>, effect remove <index|name>, effect list, help")
                    print("Available effects:", ", ".join(effect_classes.keys()))
                else:
                    print("Unknown command")
        except KeyboardInterrupt:
            print("\nExiting.")
            import numpy; numpy.random.randint()