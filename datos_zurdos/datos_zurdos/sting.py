"""Golpe de sonido de la entrada (3 s). Uso: python3 sting.py sting.wav"""
import sys, wave
import numpy as np

SR = 44100
n = int(3.0 * SR); t = np.arange(n) / SR
rng = np.random.default_rng(3)
wh = np.convolve(rng.standard_normal(n), np.ones(30) / 30, "same") * np.clip(t / 0.9, 0, 1) ** 2 * (t < 0.95) * 0.5
x = wh.copy()

def hit(at, gain, chord, kick=True):
    s0 = int(at * SR); tt = t[:n - s0]; h = np.zeros(n)
    for f in chord:
        h[s0:] += np.sin(2 * np.pi * f * tt) * np.exp(-tt * 1.6) * 0.18 * gain
    if kick:
        k = 110 * np.exp(-tt * 25) + 45
        h[s0:] += np.sin(2 * np.pi * np.cumsum(k) / SR) * np.exp(-tt * 8) * 0.7 * gain
    return h

x += hit(0.92, 1.0, (220, 261.6, 329.6, 440))   # logo completo
x += hit(1.32, 0.6, (440, 523.3, 659.3), kick=False)  # aparece la sección
x *= np.minimum(1, (3.0 - t) / 0.6)
x /= np.max(np.abs(x)) * 1.1
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.stack([x, x], 1) * 32767).astype(np.int16).tobytes())
