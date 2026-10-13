#!/usr/bin/env python3
"""Regenerate the built-in screenshot sounds (assets/sounds/*.wav).

Pure standard library (no numpy), deterministic output (fixed RNG seed), so
the shipped WAVs can always be rebuilt byte-for-byte:

    python3 tools/gen_sounds.py
"""
import math
import os
import random
import struct
import wave

SR = 44100
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sounds")


def buf(seconds):
    return [0.0] * int(SR * seconds)


def lowpass(x, fc):
    a = 1.0 - math.exp(-2.0 * math.pi * fc / SR)
    y, s = [], 0.0
    for v in x:
        s += a * (v - s)
        y.append(s)
    return y


def highpass(x, fc):
    lp = lowpass(x, fc)
    return [a - b for a, b in zip(x, lp)]


def mix_in(dst, src, start_s, gain=1.0):
    off = int(start_s * SR)
    for i, v in enumerate(src):
        j = off + i
        if 0 <= j < len(dst):
            dst[j] += v * gain


def noise_click(rng, dur, tau, lo, hi, thump_hz=0.0, thump_tau=0.0, thump_gain=0.0):
    """Band-limited noise burst with exponential decay, plus optional low 'thump'."""
    n = int(SR * dur)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    band = lowpass(highpass(raw, lo), hi)
    out = []
    for i, v in enumerate(band):
        t = i / SR
        env = math.exp(-t / tau)
        s = v * env
        if thump_gain:
            s += thump_gain * math.sin(2 * math.pi * thump_hz * t) * math.exp(-t / thump_tau)
        out.append(s)
    return out


def tone(freq, dur, tau, attack=0.004, harmonics=((1, 1.0),)):
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        env = min(1.0, t / attack) * math.exp(-t / tau)
        s = sum(g * math.sin(2 * math.pi * freq * h * t) for h, g in harmonics)
        out.append(s * env)
    return out


def square(freq, dur, tau):
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        env = min(1.0, t / 0.002) * math.exp(-t / tau)
        out.append((1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0) * env)
    return out


def finish(x, peak=0.98, fade_out=0.01, drive=4.0):
    # Soft-clip ("loudness maximiser"): short clicks have a low average level
    # even at full peak, so push them into a tanh curve, then re-peak to ~0 dBFS.
    m = max(abs(v) for v in x) or 1.0
    x = [math.tanh(drive * v / m) for v in x]
    m = max(abs(v) for v in x) or 1.0
    x = [v * peak / m for v in x]
    fo = int(SR * fade_out)
    for i in range(min(fo, len(x))):
        x[len(x) - 1 - i] *= i / fo
    return x


def write(name, x):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in x))
    print("wrote", os.path.normpath(path), f"{len(x) / SR:.3f}s")


def make_shutter(rng):
    # DSLR-style: mirror-up click, short mechanical rustle, mirror-down click.
    x = buf(0.26)
    mix_in(x, noise_click(rng, 0.06, 0.006, 900, 7000, 170, 0.012, 0.6), 0.0, 1.0)
    rustle = noise_click(rng, 0.07, 0.03, 400, 2500)
    mix_in(x, rustle, 0.012, 0.08)
    mix_in(x, noise_click(rng, 0.07, 0.008, 700, 6000, 140, 0.015, 0.7), 0.085, 0.85)
    return finish(x)


def make_soft_click(rng):
    x = buf(0.09)
    mix_in(x, noise_click(rng, 0.08, 0.005, 500, 3500, 220, 0.01, 0.5), 0.0)
    return finish(x)


def make_chime(_rng):
    x = buf(0.65)
    harm = ((1, 1.0), (2, 0.18), (3, 0.05))
    mix_in(x, tone(1568.0, 0.5, 0.16, harmonics=harm), 0.0, 0.8)    # G6
    mix_in(x, tone(2093.0, 0.55, 0.2, harmonics=harm), 0.09, 0.8)   # C7
    return finish(x, fade_out=0.05)


def make_retro(_rng):
    x = buf(0.16)
    for k, f in enumerate((880.0, 1320.0, 1760.0)):
        mix_in(x, square(f, 0.045, 0.03), 0.04 * k, 0.35)
    return finish(lowpass(x, 6000))


def main():
    rng = random.Random(0x5A5020)
    write("shutter.wav", make_shutter(rng))
    write("soft_click.wav", make_soft_click(rng))
    write("chime.wav", make_chime(rng))
    write("retro.wav", make_retro(rng))


if __name__ == "__main__":
    main()
