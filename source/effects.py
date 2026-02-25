import numpy as np
from numba import njit

EFFECT_PARAMS = {
    # BITCRUSH
    "BITCRUSH_BITS": 8,
    "BITCRUSH_DOWNSAMPLE": 6,

    # Saturation
    "SAT_DRIVE": 2.0,
    "SAT_EXCITE": 0.15,

    # Reverb
    "REV_WET": 0.12,
    "REV_FEEDBACK": 0.35,
    "REV_D1": 1200,
    "REV_D2": 1700,
    "REV_D3": 900,

    # Pitch shift
    "PITCH_SEMITONES": 0.0,
    "FORMANT_SEMITONES": 0.0,
    "GRANP_GRAIN": 480,

    # Granular delay
    "GRAN_GRAIN": 800,
    "GRAN_JITTER": 0.3,
    "GRAN_MIX": 0.25,
}

# ---------------- Effect Implementations ----------------

def effect_none(chunk):
    return chunk

# HPF
hpf_prev_in = 0.0
hpf_prev_out = 0.0
hpf_alpha = 0.0

def init_hpf(sample_rate, cutoff=100.0):
    global hpf_alpha
    rc = 1.0 / (2 * np.pi * cutoff)
    dt = 1.0 / sample_rate
    hpf_alpha = rc / (rc + dt)

init_hpf(48000, cutoff=120.0)

@njit
def hpf_loop(chunk, prev_in, prev_out, alpha):
    out = np.empty_like(chunk)

    for i in range(len(chunk)):
        x = chunk[i]
        y = alpha * (prev_out + x - prev_in)

        out[i] = y
        prev_in = x
        prev_out = y

    return out, prev_in, prev_out

# ---------------- Bitcrusher ----------------
@njit
def __bitcrush_loop(chunk, levels, downsample, counter, last):
    out = np.empty_like(chunk)
    for i in range(len(chunk)):
        if counter == 0:
            last = np.round(chunk[i] * levels) / levels
        out[i] = last
        counter += 1
        if counter >= downsample:
            counter = 0
    return out, counter, last

bitcrush_counter = 0
bitcrush_last = 0.0

def effect_bitcrush(chunk):
    global bitcrush_counter, bitcrush_last
    levels = 2 ** EFFECT_PARAMS["BITCRUSH_BITS"]
    out, bitcrush_counter, bitcrush_last = __bitcrush_loop(
        chunk.ravel(), levels, EFFECT_PARAMS["BITCRUSH_DOWNSAMPLE"], bitcrush_counter, bitcrush_last
    )
    return out.reshape(chunk.shape)

# ---------------- SAT/EXCITE ----------------
@njit
def _saturation_loop(chunk, drive, excite):
    out = np.empty_like(chunk)
    prev = 0.0
    for i in range(len(chunk)):
        boosted = chunk[i] + excite * (chunk[i] - prev)
        out[i] = np.tanh(boosted * drive)
        prev = chunk[i]
    return out

def effect_saturation(chunk):
    return _saturation_loop(
        chunk.ravel(),
        EFFECT_PARAMS["SAT_DRIVE"],
        EFFECT_PARAMS["SAT_EXCITE"]
    ).reshape(chunk.shape)


# ---------------- REVERB ----------------
reverb_buf = np.zeros(48000, dtype=np.float32)
reverb_idx = 0

@njit
def _reverb_loop(chunk, buf, idx, wet, fb, delays):
    out = np.empty_like(chunk)
    buf_len = len(buf)
    for i in range(len(chunk)):
        dry = chunk[i]
        acc = 0.0
        for d in delays:
            acc += buf[(idx - d) % buf_len]
        acc /= len(delays)
        buf[idx] = dry + acc * fb
        out[i] = dry * (1 - wet) + acc * wet
        idx = (idx + 1) % buf_len
    return out, buf, idx

def effect_reverb(chunk):
    global reverb_buf, reverb_idx
    delays = [
        int(EFFECT_PARAMS["REV_D1"]),
        int(EFFECT_PARAMS["REV_D2"]),
        int(EFFECT_PARAMS["REV_D3"])
    ]
    out, reverb_buf, reverb_idx = _reverb_loop(
        chunk.ravel(),
        reverb_buf,
        reverb_idx,
        EFFECT_PARAMS["REV_WET"],
        EFFECT_PARAMS["REV_FEEDBACK"],
        np.array(delays, dtype=np.int32)
    )
    return out.reshape(chunk.shape)


# ---------------- PITCH SHIFT ----------------
GRANP_GRAIN = 480  # 10ms @ 48kHz default
GRANP_NUM = 4

granp_buf = np.zeros(96000, dtype=np.float32)
granp_write = 0

granp_reads = np.zeros(GRANP_NUM, dtype=np.float32)
granp_phase = np.zeros(GRANP_NUM, dtype=np.int32)

granp_window = np.hanning(GRANP_GRAIN).astype(np.float32)

from numba import njit
import numpy as np

@njit
def _granular4_loop(
    chunk,
    buf,
    write_idx,
    reads,
    phases,
    grain,
    window,
    ratio
):
    out = np.zeros_like(chunk)
    buf_len = len(buf)
    num = len(reads)
    spacing = grain // num

    for i in range(len(chunk)):

        # write incoming audio
        buf[write_idx] = chunk[i]
        write_idx = (write_idx + 1) % buf_len

        sample_out = 0.0

        for g in range(num):

            # reset grain if finished
            if phases[g] >= grain:
                phases[g] = 0
                reads[g] = (write_idx - grain) % buf_len

            # read with linear interpolation
            base = int(reads[g])
            frac = reads[g] - base

            s0 = buf[base % buf_len]
            s1 = buf[(base + 1) % buf_len]
            sample = s0 * (1 - frac) + s1 * frac

            # apply window
            sample *= window[phases[g]]

            sample_out += sample

            # advance
            reads[g] += ratio
            phases[g] += 1

        out[i] = sample_out

    return out, write_idx, reads, phases

def effect_granular_pitch(chunk):
    global granp_buf
    global granp_write
    global granp_reads
    global granp_phase
    global granp_window
    global GRANP_GRAIN

    global hpf_prev_in
    global hpf_prev_out
    global hpf_alpha

    semitones = EFFECT_PARAMS["PITCH_SEMITONES"]
    ratio = 2 ** (semitones / 12)

    desired_grain = int(EFFECT_PARAMS["GRANP_GRAIN"])
    if desired_grain != GRANP_GRAIN:
        GRANP_GRAIN = desired_grain
        granp_window = np.hanning(GRANP_GRAIN).astype(np.float32)

    # 🔥 HIGH-PASS FIRST
    filtered, hpf_prev_in, hpf_prev_out = hpf_loop(
        chunk.ravel(),
        hpf_prev_in,
        hpf_prev_out,
        hpf_alpha
    )

    # THEN granular
    out, granp_write, granp_reads, granp_phase = _granular4_loop(
        filtered,
        granp_buf,
        granp_write,
        granp_reads,
        granp_phase,
        GRANP_GRAIN,
        granp_window,
        ratio
    )

    out *= 0.5

    formant_shift = EFFECT_PARAMS["FORMANT_SEMITONES"]

    if formant_shift != 0.0:
        global lpc_buffer, lpc_write

        for i in range(len(out)):
            lpc_buffer[lpc_write] = out[i]
            lpc_write += 1

            if lpc_write >= LPC_FRAME:
                processed = process_lpc_frame(lpc_buffer.copy(), formant_shift)

                out[i - LPC_FRAME + 1 : i + 1] = processed
                lpc_write = LPC_FRAME - LPC_HOP
                lpc_buffer[:LPC_HOP] = lpc_buffer[LPC_HOP:]


    return out.reshape(chunk.shape)

# ----------------- FORMANT SHIFT ----------------
LPC_FRAME = 960
LPC_HOP = 480
LPC_ORDER = 16

lpc_buffer = np.zeros(LPC_FRAME, dtype=np.float32)
lpc_out_buffer = np.zeros(LPC_FRAME, dtype=np.float32)

lpc_write = 0
lpc_out_read = 0

from numba import njit
import numpy as np

@njit
def levinson_durbin(r, order):
    a = np.zeros(order + 1, dtype=np.float32)
    e = r[0]

    a[0] = 1.0

    for i in range(1, order + 1):
        acc = 0.0
        for j in range(1, i):
            acc += a[j] * r[i - j]

        k = -(r[i] + acc) / (e + 1e-9)

        a_new = a.copy()
        for j in range(1, i):
            a_new[j] = a[j] + k * a[i - j]

        a_new[i] = k
        a = a_new

        e *= (1.0 - k * k)

    return a

@njit
def autocorr(x, order):
    r = np.zeros(order + 1, dtype=np.float32)

    for lag in range(order + 1):
        acc = 0.0
        for i in range(len(x) - lag):
            acc += x[i] * x[i + lag]
        r[lag] = acc

    return r

@njit
def warped_lpc_filter(x, a, alpha):
    order = len(a) - 1
    y = np.zeros_like(x)

    # state buffer
    state = np.zeros(order, dtype=np.float32)

    for n in range(len(x)):
        xn = x[n]
        acc = xn

        for k in range(order):
            acc -= a[k + 1] * state[k]

        # shift state with warping
        prev = acc
        for k in range(order):
            tmp = state[k]
            state[k] = prev + alpha * (tmp - prev)
            prev = tmp

        y[n] = acc

    return y

@njit
def lpc_filter(x, a):
    y = np.zeros_like(x)
    order = len(a) - 1

    for n in range(len(x)):
        y[n] = x[n]
        for k in range(1, order + 1):
            if n - k >= 0:
                y[n] -= a[k] * y[n - k]

    return y

@njit
def process_lpc_frame(frame, formant_semitones):
    # convert semitones to warp coefficient
    # small range is important
    alpha = 0.6 * (formant_semitones / 12.0)

    if alpha > 0.8:
        alpha = 0.8
    if alpha < -0.8:
        alpha = -0.8

    r = autocorr(frame, LPC_ORDER)
    a = levinson_durbin(r, LPC_ORDER)

    return warped_lpc_filter(frame, a, alpha)


# ---------------- GRANULAR DELAY ----------------
gran_buf = np.zeros(96000, dtype=np.float32)
gran_write = 0
gran_read = 0
gran_pos = 0

@njit
def _granular_loop(chunk, buf, write_idx, read_idx, pos, grain, jitter, mix):
    out = np.empty_like(chunk)
    buf_len = len(buf)
    for i in range(len(chunk)):
        dry = chunk[i]

        # write incoming sample
        buf[write_idx] = dry
        write_idx = (write_idx + 1) % buf_len

        # if starting a new grain, pick new jittered offset
        if pos == 0:
            jitter_amount = int(grain * jitter)
            offset = grain + np.random.randint(-jitter_amount, jitter_amount + 1)
            read_idx = (write_idx - offset) % buf_len

        # read from buffer
        wet = buf[read_idx]
        read_idx = (read_idx + 1) % buf_len

        # advance grain position
        pos += 1
        if pos >= grain:
            pos = 0

        out[i] = dry * (1 - mix) + wet * mix

    return out, buf, write_idx, read_idx, pos

def effect_granular(chunk):
    global gran_buf, gran_write, gran_read, gran_pos
    grain = int(EFFECT_PARAMS["GRAN_GRAIN"])
    jitter = EFFECT_PARAMS["GRAN_JITTER"]
    mix = EFFECT_PARAMS["GRAN_MIX"]

    out, gran_buf, gran_write, gran_read, gran_pos = _granular_loop(
        chunk.ravel(),
        gran_buf,
        gran_write,
        gran_read,
        gran_pos,
        grain,
        jitter,
        mix
    )
    return out.reshape(chunk.shape)

# ---------------- Dictionary ----------------
EFFECTS = {
    "none": effect_none,
    "bitcrush": effect_bitcrush,
    "saturation": effect_saturation,
    "reverb": effect_reverb,
    "pitch": effect_granular_pitch,
    "granular": effect_granular,
}
