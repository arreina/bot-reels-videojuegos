import numpy as np, wave, sys
SR = 44100
DUR = float(sys.argv[2])
BPM = 92
beat = 60 / BPM
n = int(SR * DUR)
t = np.arange(n) / SR
out = np.zeros((n, 2))

def note(f): return 440 * 2 ** ((f - 69) / 12)
# Am - F - C - G (one chord per bar)
CH = [[57, 60, 64], [53, 57, 60], [48, 55, 64], [55, 59, 62]]
BASS = [45, 41, 36, 43]
bar = 4 * beat

rng = np.random.default_rng(1)
for b in range(int(DUR / bar) + 1):
    s0 = int(b * bar * SR); s1 = min(n, int((b + 1) * bar * SR) + int(0.3 * SR))
    if s0 >= n: break
    tt = np.arange(s1 - s0) / SR
    env = np.minimum(1, tt / 0.6) * np.exp(-tt * 0.25)
    pad = np.zeros_like(tt)
    for m in CH[b % 4]:
        f = note(m)
        for det in (-0.12, 0.12):
            ph = 2 * np.pi * f * (1 + det / 100) * tt
            pad += 0.5 * np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    pad *= env * 0.05
    out[s0:s1, 0] += pad; out[s0:s1, 1] += np.roll(pad, 200)
    # bass on each beat
    for k in range(4):
        q0 = s0 + int(k * beat * SR); q1 = min(n, q0 + int(beat * SR))
        if q0 >= n: break
        qt = np.arange(q1 - q0) / SR
        bs = np.sin(2 * np.pi * note(BASS[b % 4]) * qt) * np.exp(-qt * 4) * 0.22
        out[q0:q1] += bs[:, None]

# drums: kick on 1 & 3, snare-ish on 2 & 4, hats 8ths (start after 1 bar)
for k in range(int(DUR / beat * 2)):
    s0 = int(k * beat / 2 * SR)
    if s0 >= n: break
    L = min(n - s0, int(0.4 * SR)); tt = np.arange(L) / SR
    if k % 4 == 0:
        f = 110 * np.exp(-tt * 25) + 45
        ph = 2 * np.pi * np.cumsum(f) / SR
        out[s0:s0 + L] += (np.sin(ph) * np.exp(-tt * 9) * 0.55)[:, None]
    if k % 4 == 2 and k >= 8:
        nz = rng.standard_normal(L) * np.exp(-tt * 18) * 0.16
        out[s0:s0 + L] += nz[:, None]
    if k >= 8:
        Lh = min(L, int(0.05 * SR))
        hh = rng.standard_normal(Lh) * np.exp(-np.arange(Lh) / SR * 90) * 0.05
        hh = np.diff(np.concatenate([[0], hh]))  # brighten
        out[s0:s0 + Lh, 0] += hh; out[s0:s0 + Lh, 1] += hh * 0.8

# fades
fi = np.minimum(1, t / 1.0); fo = np.minimum(1, (DUR - t) / 2.0)
out *= (fi * fo)[:, None]
out /= np.max(np.abs(out)) * 1.12
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((out * 32767).astype(np.int16).tobytes())
