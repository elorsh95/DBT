"""Sound for the animation, numpy only: every cue from sfx(t, kind, gain) is synthesised here (no sound files),
plus optional music the user supplies (CONFIG.music). The mix is mastered to -14 LUFS, peaks at most -1 dBTP.

render.py calls build() on its own before preview/full. By hand:
  python audio.py                 rebuild out/audio.wav from out/cues.json (written by render.py preview/full)
  python audio.py beat song.mp3   tempo, first beat and first downbeat of a song (for the beat grid)
  python audio.py demo            out/sfx-demo.wav: every sound kind in a row, one per half second"""
import json, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np

for _s in (sys.stdout, sys.stderr):   # Hebrew in messages must not crash a Windows console
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
SR = 48000
TARGET_LUFS, PEAK_DBTP = -14.0, -1.0
rng = np.random.default_rng(11)


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


FF = find_ffmpeg()
N = lambda d: int(d * SR)
tt = lambda d: np.arange(N(d)) / SR


# ---------- building blocks (zero-phase FFT filters: fine for short one-shots) ----------
def _mask(x, lo=None, hi=None, order=2):
    n = len(x); X = np.fft.rfft(x, 2 * n); f = np.fft.rfftfreq(2 * n, 1 / SR) + 1e-9; g = np.ones_like(f)
    if hi: g /= np.sqrt(1 + (f / hi) ** (2 * order))
    if lo: g /= np.sqrt(1 + (lo / f) ** (2 * order))
    return np.fft.irfft(X * g)[:n]
lp = lambda x, f, o=2: _mask(x, hi=f, order=o)
hp = lambda x, f, o=2: _mask(x, lo=f, order=o)
bp = lambda x, lo, hi, o=2: _mask(x, lo=lo, hi=hi, order=o)
def norm(x, g=1.0): m = np.abs(x).max(); return x * (g / m) if m > 0 else x
def noise(d): return rng.standard_normal(N(d))
def dec(d, k): return np.exp(-tt(d) * k)
def att(d, a): return np.clip(tt(d) / a, 0, 1)
def hump(d, p=1.5): return np.sin(np.pi * np.clip(tt(d) / d, 0, 1)) ** p
def sweep(f0, f1, d, curve=1.0):
    t = tt(d); f = f0 * (f1 / f0) ** ((t / d) ** curve); return np.sin(2 * np.pi * np.cumsum(f) / SR)
def tone(f, d, k, h=(1,), amps=(1,)):
    t = tt(d); return sum(a * np.sin(2 * np.pi * f * m * t) for m, a in zip(h, amps)) * np.exp(-t * k)
def add(*xs):
    L = max(len(x) for x in xs); out = np.zeros(L)
    for x in xs: out[:len(x)] += x
    return out
def seq(parts):   # [(offset_s, signal)]
    L = max(N(o) + len(x) for o, x in parts); out = np.zeros(L)
    for o, x in parts: out[N(o):N(o) + len(x)] += x
    return out
def swept_noise(d, f0, f1, bands=8, width=0.5):
    """noise whose band glides from f0 to f1: crossfade of fixed bands, each peaking at its moment"""
    out = np.zeros(N(d)); x = noise(d); u = tt(d) / d
    for i in range(bands):
        c = f0 * (f1 / f0) ** (i / (bands - 1)); centre = i / (bands - 1)
        out += bp(x, c * (1 - width / 2), c * (1 + width)) * np.exp(-((u - centre) / (0.9 / bands)) ** 2)
    return out
def bell(freqs, d, k, part=(1, 2.76, 5.4), pamp=(1, .35, .12)):
    return norm(sum(tone(f, d, k, part, pamp) for f in freqs) * att(d, 0.002))
def click(f=2600, d=0.035, thump=110):
    t = tt(d); n = noise(d) * np.exp(-t * 180)
    return norm(0.35 * np.convolve(n, [.5, -.5], 'same') + 0.4 * np.sin(2 * np.pi * f * t) * np.exp(-t * 120)
                + 0.8 * np.sin(2 * np.pi * thump * t) * np.exp(-t * 60))
def pop(f0=700, f1=250, d=0.09):
    return norm(sweep(f0, f1, d, 0.6) * dec(d, 38) * att(d, 0.002) + 0.15 * hp(noise(d), 3000) * dec(d, 300))
def boom(d=0.45, f0=130, f1=42, body=1.0):
    s = sweep(f0, f1, d, 0.35) * dec(d, 7) * att(d, 0.003)
    return norm(np.tanh(2.2 * add(body * s, 0.5 * lp(noise(d), 1400) * dec(d, 40))))


def make(kind):
    k = rng.uniform(0.93, 1.07)   # every cue gets its own small pitch offset, so repeats never sound identical
    if kind == 'click': return click(2600 * k)
    if kind == 'tick': return 0.6 * click(3800 * k, 0.02, 260)
    if kind == 'count': return 0.5 * click(4400 * k, 0.014, 320)
    if kind == 'key':
        return norm(0.6 * bp(noise(0.03), 1500, 6000) * dec(0.03, 160) + 0.7 * np.sin(2 * np.pi * 180 * k * tt(0.03)) * dec(0.03, 90)
                    + 0.25 * tone(2500 * k, 0.03, 200))
    if kind == 'pop': return pop(700 * k, 250 * k)
    if kind == 'popHi': return pop(1400 * k, 600 * k, 0.07)
    if kind == 'hit':   # type slam: short low body + a click on top
        return norm(add(boom(0.28, 170 * k, 58 * k, 0.9), 0.5 * click(3000 * k, 0.02, 140 * k), 0.3 * lp(noise(0.05), 2500) * dec(0.05, 70)))
    if kind == 'impact': return boom(0.5, 130 * k, 42 * k)
    if kind == 'sub': return norm(np.tanh(2.5 * add(sweep(72 * k, 27, 1.2, 0.5) * dec(1.2, 2.6) * att(1.2, 0.004), 0.35 * lp(noise(0.08), 900) * dec(0.08, 50))))
    if kind == 'thud': return norm(sweep(95 * k, 48, 0.2, 0.6) * dec(0.2, 22) * att(0.2, 0.002) + 0.2 * lp(noise(0.2), 600) * dec(0.2, 60))
    if kind == 'whoosh': return norm(lp(swept_noise(0.34, 400 * k, 2600 * k), 5000) * hump(0.34))
    if kind == 'swish': return norm(swept_noise(0.2, 1500 * k, 5500 * k) * hump(0.2))
    if kind == 'rise':
        d = 0.5; x = 0.4 * sweep(180 * k, 900 * k, d, 1.4) * att(d, d) ** 2 + 0.6 * norm(swept_noise(d, 500, 6000)) * att(d, d) ** 2
        return norm(x)
    if kind == 'ding': return norm(seq([(0, bell([1760 * k], 0.8, 5)), (0.11, bell([2637 * k], 0.9, 4.5))]))
    if kind == 'chime': return norm(seq([(i * 0.045, bell([f * k], 1.1, 3.5)) for i, f in enumerate([1046.5, 1318.5, 1568, 2093])]))
    if kind == 'success': return norm(seq([(0, tone(1318.5, 0.5, 8, (1, 2), (1, .15))), (0.085, tone(1975.5, 0.6, 7, (1, 2), (1, .12)))]))
    if kind == 'sparkle': return norm(seq([(i * 0.055, tone((3000 + i * 500) * k, 0.12, 45)) for i in range(6)]))
    if kind == 'glitch':
        d = 0.24; t = tt(d); x = np.sign(np.sin(2 * np.pi * 600 * k * t)) * 0.4 + noise(d)
        x = np.round(x * 3) / 3; gate = (np.sin(2 * np.pi * 38 * t) > -0.2).astype(float)
        return norm(bp(x, 400, 7000) * gate * (1 - att(d, d) ** 3))
    if kind == 'shutter':
        return norm(seq([(0, click(1800, 0.03, 90)), (0.045, 0.8 * click(2400, 0.03, 120)), (0, 0.3 * bp(noise(0.08), 2000, 8000) * dec(0.08, 50))]))
    if kind == 'boing':
        d = 0.55; t = tt(d); f = 190 * k * (1 + 0.35 * np.sin(2 * np.pi * 11 * t) * np.exp(-t * 4)) * (1 + 0.6 * t)
        return norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * dec(d, 6) * att(d, 0.005))
    raise ValueError(f"unknown sound kind '{kind}'. Kinds: {', '.join(LEVEL)}")


# loudness of each kind in dB relative to the reference (the music when there is music). Air sounds stay quiet.
LEVEL = dict(click=-13, tick=-18, count=-21, key=-19, pop=-15, popHi=-16, hit=-9, impact=-7, sub=-7, thud=-13,
             whoosh=-21, swish=-22, rise=-18, ding=-10, chime=-13, success=-12, sparkle=-15, glitch=-16, shutter=-15, boing=-13)


def arms(x):   # RMS of the active part, in dB
    e = np.convolve(x ** 2, np.ones(480) / 480, 'same'); act = e > e.max() * 0.05
    return 10 * np.log10(e[act].mean() + 1e-12)


def room(x):   # small room: convolution with 0.35 s of decaying, darkened noise (wet only)
    ir = lp(noise(0.35) * dec(0.35, 14), 5000); ir[:N(0.004)] = 0
    n = len(x) + len(ir); size = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size))[:len(x)]
    return norm(y, 1) * np.abs(x).max() * 0.18


def load(path, sr=SR, start=0.0, dur=None, ch=1):
    cmd = [FF, "-v", "quiet", "-ss", str(start)] + (["-t", str(dur)] if dur else []) + ["-i", str(path), "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"]
    x = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).astype(np.float64)
    return x.reshape(-1, ch) if ch > 1 else x


def music_track(root, cfg, L):
    m = cfg.get("music") or {}
    if isinstance(m, str): m = {"file": m}
    path = root / m["file"]
    if not path.exists():
        raise FileNotFoundError(f"music file not found: {path}")
    dur = L / SR; xf = N(0.08)
    x = load(path, start=float(m.get("start", 0)), dur=dur + 0.2, ch=2)
    if len(x) < L: x = np.pad(x, ((0, L - len(x)), (0, 0)))
    if cfg.get("loop"):   # the audio right after the loop point is crossfaded into the head, so the seam plays through
        tail = x[L:L + xf].copy(); x = x[:L].copy()
        if len(tail) == xf:
            fin = np.sin(np.linspace(0, np.pi / 2, xf))[:, None] ** 2; x[:xf] = x[:xf] * fin + tail * (1 - fin)
    else:
        x = x[:L].copy(); fo = min(L, N(0.6)); x[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 2
    return x * 10 ** (float(m.get("gain", 0)) / 20)


def onset_snap(mono):
    """move a cue up to 25 ms onto the nearest measured transient of the music"""
    env = np.convolve(np.abs(mono), np.ones(96) / 96, "same"); dif = np.maximum(np.diff(env, prepend=env[0]), 0)
    def snap(t, win=0.025):
        a, b = N(max(0, t - win)), N(t + win); b = min(b, len(dif))
        return (a + int(np.argmax(dif[a:b]))) / SR if b > a else t
    return snap


def measure(st, out):
    tmp = out.with_name("_raw.wav"); write_wav(tmp, st, clip=False)
    m = subprocess.run([FF, "-hide_banner", "-i", str(tmp), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    tmp.unlink(); js = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    return float(js["input_i"]), float(js["input_tp"])


def limit(st, ceiling_db=-1.6, look=0.004, rel=0.05):
    """transparent peak limiter: gain = windowed minimum of the needed reduction, smoothed"""
    g = np.minimum(1.0, 10 ** (ceiling_db / 20) / np.maximum(np.abs(st).max(1), 1e-9))
    w = max(2, N(look)); gp = np.pad(g, (w // 2, w - w // 2 - 1), constant_values=1.0)
    gmin = np.lib.stride_tricks.sliding_window_view(gp, w).min(1)
    k = max(2, N(rel)); gs = np.convolve(np.pad(gmin, (k // 2, k - k // 2 - 1), constant_values=1.0), np.ones(k) / k, "valid")
    return st * np.minimum(gs, gmin)[:, None]


def master(st, out):
    """to -14 LUFS: gain, a peak limiter if the peaks would pass -1 dBTP, then a final check (only ever turns down)"""
    li, tp = measure(st, out)
    if li <= -70:
        write_wav(out, st); return li
    st = st * 10 ** ((TARGET_LUFS - li) / 20)
    if tp + TARGET_LUFS - li > PEAK_DBTP:
        st = limit(st)
        li, tp = measure(st, out)
        st = st * 10 ** (min(0.0, TARGET_LUFS - li, PEAK_DBTP - tp) / 20)
        li += min(0.0, TARGET_LUFS - li, PEAK_DBTP - tp)
    else:
        li = TARGET_LUFS
    write_wav(out, st)
    return li


def write_wav(path, st, clip=True):
    if not clip:   # measurement copy: scale down instead of clipping, the caller corrects by the same factor
        st = st / max(1.0, np.abs(st).max())
    st = np.clip(st, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((st * 32767).astype("<i2").tobytes())


def build(root, cfg, cues):
    root = Path(root); L = N(float(cfg["DUR"]))
    mus = music_track(root, cfg, L) if cfg.get("music") else None
    ref = arms(mus.mean(1)) if mus is not None else -20.0
    snap = onset_snap(mus.mean(1)) if mus is not None and cfg.get("snap", True) else (lambda t: t)
    gmax = {}
    for _, kind, g in cues: gmax[kind] = max(gmax.get(kind, 0), g)
    bus = np.zeros(L + N(2))
    for t, kind, g in cues:
        x = make(kind); x = x * 10 ** ((ref + LEVEL[kind] - arms(x)) / 20) * (g / gmax[kind])
        i = N(snap(float(t))); j = min(len(bus), i + len(x)); bus[i:j] += x[:j - i]
    if cues: bus = bus + room(bus)
    if cfg.get("loop"):   # tails that run past the end wrap to the start
        bus[:N(2)] += bus[L:]
    bus = bus[:L]
    st = np.stack([bus, bus], 1) + (mus if mus is not None else 0)
    out = root / "out" / "audio.wav"; out.parent.mkdir(exist_ok=True)
    lufs = master(st, out)
    print(f"audio {out}: {len(cues)} cues, music {'yes' if mus is not None else 'no'}, {lufs:.1f} LUFS")
    return out


# ---------- beat grid of a song ----------
def beat_grid(path):
    sr, hop, n = 22050, 256, 1024
    x = load(path, sr=sr).astype(np.float32)
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    S_ = np.log1p(10 * np.abs(np.fft.rfft(fr, axis=1)))
    env = np.maximum(0, np.diff(S_, axis=0)).sum(1); env -= np.convolve(env, np.ones(16) / 16, "same"); env = np.maximum(env, 0)
    fps = sr / hop; e = env - env.mean()
    ac = np.correlate(e, e, "full")[len(e) - 1:]; lags = np.arange(len(ac)); bpm = 60 * fps / np.maximum(lags, 1)
    m = (bpm > 80) & (bpm < 170); i = lags[m][np.argmax(ac[m])]
    y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]; tempo = 60 * fps / (i + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2))
    period = 60 / tempo; t_end = len(env) / fps
    def score(phase, step):
        ts = np.arange(phase, t_end, step); idx = np.clip((ts * fps).round().astype(int), 0, len(env) - 1); return env[idx].mean()
    phases = np.linspace(0, period, 200, endpoint=False); ph = phases[np.argmax([score(p, period) for p in phases])]
    db = ph + int(np.argmax([score(ph + k * period, 4 * period) for k in range(4)])) * period
    return tempo, ac[i] / ac[0], ph, db, t_end


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "beat":
        tempo, conf, ph, db, total = beat_grid(sys.argv[2])
        print(f"{tempo:.2f} BPM (confidence {conf:.2f}), first beat {ph:.3f}s, first downbeat {db:.3f}s, song {total:.1f}s")
        print(f"downbeats: {db:.3f} + {4 * 60 / tempo:.4f} * k seconds. Put one of them in CONFIG.music.start, and bpm: {round(tempo)} in CONFIG.")
    elif len(sys.argv) > 1 and sys.argv[1] == "demo":
        root = Path(__file__).resolve().parent; (root / "out").mkdir(exist_ok=True)
        kinds = list(LEVEL); cfg = {"DUR": 0.5 * len(kinds) + 1}
        build(root, cfg, [[0.5 * i + 0.2, k_, 1] for i, k_ in enumerate(kinds)])
        (root / "out" / "audio.wav").replace(root / "out" / "sfx-demo.wav"); print("order:", ", ".join(kinds))
    else:
        root = Path(__file__).resolve().parent; data = json.loads((root / "out" / "cues.json").read_text(encoding="utf-8"))
        build(root, data["config"], data["cues"])
