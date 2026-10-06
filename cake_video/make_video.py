#!/usr/bin/env python3
"""Render an animated showcase video of a homemade cake from still photos.

Ken Burns camera moves, cross-dissolves, falling powdered-sugar particles,
Hebrew titles and a synthesized piano soundtrack, encoded with ffmpeg.

Usage: python3 make_video.py PHOTO_DIR OUTPUT.mp4
"""
import math
import os
import subprocess
import sys
import wave
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1350          # 4:5 – Instagram / WhatsApp friendly
FPS = 30
XFADE = 0.9                # seconds of cross-dissolve between scenes
FONT_BOLD = "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf"
FONT_REG = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"
CREAM = (255, 246, 230)
GOLD = (222, 176, 98)

# (file prefix, duration, zoom start, zoom end, pan from (x, y), pan to, caption)
# Pan values are the crop centre in normalised image coordinates.
SCENES = [
    ("040bd881", 3.6, 1.18, 1.04, (0.50, 0.55), (0.48, 0.52), "קלאסיקה ביתית"),
    ("83e283f8", 3.2, 1.00, 1.14, (0.45, 0.52), (0.48, 0.48), "שמיכה של אבקת סוכר"),
    ("986db8bd", 3.8, 1.05, 1.05, (0.30, 0.50), (0.68, 0.50), "קרום זהוב ופריך"),
    ("2003b4fa", 3.0, 1.12, 1.00, (0.40, 0.50), (0.48, 0.50), None),
    ("e0ade6da", 3.4, 1.00, 1.16, (0.50, 0.55), (0.50, 0.62), "הפרוסה הראשונה"),
    ("00e9c27d", 3.0, 1.15, 1.02, (0.48, 0.55), (0.50, 0.50), None),
    ("229d33b4", 4.0, 1.00, 1.22, (0.62, 0.50), (0.70, 0.45), "מרקם רך ואוורירי"),
    ("1fbeaf02", 3.0, 1.10, 1.00, (0.50, 0.55), (0.50, 0.50), None),
    ("d6b33118", 3.4, 1.00, 1.12, (0.50, 0.58), (0.50, 0.62), "מחכה לכוס קפה"),
    ("eb63af35", 4.6, 1.14, 1.00, (0.50, 0.55), (0.50, 0.50), None),
]
INTRO = 3.4
OUTRO_HOLD = 1.6          # extra time on the final scene for the closing title


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


# ---------------------------------------------------------------- timeline
def build_timeline():
    """Return list of (start, end) for each scene, plus total duration."""
    spans, t = [], INTRO - XFADE
    for i, s in enumerate(SCENES):
        dur = s[1] + (OUTRO_HOLD + 2.6 if i == len(SCENES) - 1 else 0)
        spans.append((t, t + dur + XFADE))
        t += dur
    return spans, t + XFADE


SPANS, TOTAL = build_timeline()
N_FRAMES = int(round(TOTAL * FPS))

# ---------------------------------------------------------------- assets (per worker)
_A = {}


def load_assets(photo_dir):
    files = {f.split("-")[0]: os.path.join(photo_dir, f) for f in os.listdir(photo_dir)}
    imgs = []
    for s in SCENES:
        im = ImageOps.exif_transpose(Image.open(files[s[0]])).convert("RGB")
        # Pre-scale so a zoom of 1.0 "covers" the frame with ~1.3x headroom.
        cover = max(W / im.width, H / im.height) * 1.3
        im = im.resize((int(im.width * cover), int(im.height * cover)), Image.LANCZOS)
        imgs.append(grade(im))
    _A["imgs"] = imgs

    # Intro backdrop: heavily blurred, darkened first photo.
    first = imgs[0].resize((W, int(W * imgs[0].height / imgs[0].width)), Image.LANCZOS)
    top = (first.height - H) // 2
    bg = first.crop((0, top, W, top + H)).filter(ImageFilter.GaussianBlur(40))
    _A["intro_bg"] = np.asarray(bg, dtype=np.float32) * 0.35

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    _A["vignette"] = (1 - 0.42 * np.clip(r - 0.45, 0, 1) ** 1.6)[..., None]
    grad = np.clip((yy - H * 0.62) / (H * 0.38), 0, 1) ** 1.4
    _A["bottom_shade"] = (1 - 0.55 * grad)[..., None]

    _A["particles"] = make_particles()
    _A["fonts"] = {
        "title": ImageFont.truetype(FONT_BOLD, 132),
        "sub": ImageFont.truetype(FONT_REG, 54),
        "cap": ImageFont.truetype(FONT_BOLD, 76),
        "end": ImageFont.truetype(FONT_BOLD, 150),
    }


def grade(im):
    """Warm, slightly contrasty bakery grade."""
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = a * np.array([1.05, 1.0, 0.92])                     # warm
    a = np.clip(a, 0, 1)
    a = a + 0.25 * (a - a ** 2) * (2 * a - 1)               # gentle S-curve
    a = 0.5 + (a - 0.5) * 1.08
    lum = a.mean(axis=2, keepdims=True)
    a = lum + (a - lum) * 1.10                              # saturation
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def make_particles(n=170, seed=7):
    rng = np.random.default_rng(seed)
    return {
        "x": rng.uniform(0, W, n), "y": rng.uniform(-H, H, n),
        "r": rng.choice([1.2, 1.6, 2.2, 3.0, 4.2], n, p=[.3, .3, .2, .13, .07]),
        "v": rng.uniform(40, 120, n), "a": rng.uniform(0.25, 0.85, n),
        "ph": rng.uniform(0, 2 * np.pi, n), "sw": rng.uniform(8, 30, n),
    }


# ---------------------------------------------------------------- rendering
def scene_frame(i, t_local, dur):
    s, im = SCENES[i], _A["imgs"][i]
    p = ease(t_local / dur)
    z = s[2] + (s[3] - s[2]) * p
    cx = s[4][0] + (s[5][0] - s[4][0]) * p
    cy = s[4][1] + (s[5][1] - s[4][1]) * p
    # zoom 1.0 = largest crop that keeps the frame aspect inside the image
    base = min(im.width / W, im.height / H)
    cw, ch = W * base / z, H * base / z
    x0 = min(max(cx * im.width - cw / 2, 0), im.width - cw)
    y0 = min(max(cy * im.height - ch / 2, 0), im.height - ch)
    fr = im.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch))
    return np.asarray(fr, dtype=np.float32)


def draw_particles(layer, t, strength):
    if strength <= 0:
        return
    P = _A["particles"]
    d = ImageDraw.Draw(layer)
    ys = (P["y"] + P["v"] * t) % (H + 40) - 20
    xs = P["x"] + P["sw"] * np.sin(t * 0.9 + P["ph"])
    for x, y, r, a in zip(xs, ys, P["r"], P["a"]):
        al = int(255 * a * strength)
        if r > 2.5:
            d.ellipse((x - r * 1.8, y - r * 1.8, x + r * 1.8, y + r * 1.8), fill=(255, 255, 255, al // 4))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, al))


def text_block(layer, lines, alpha, rise):
    """lines: [(text, font, color, y_centre)]. Draws with a soft shadow."""
    if alpha <= 0:
        return
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    txt = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sd, td = ImageDraw.Draw(shadow), ImageDraw.Draw(txt)
    for text, font, color, yc in lines:
        if text == "—":
            w = 220 * alpha
            td.line((W / 2 - w / 2, yc + rise, W / 2 + w / 2, yc + rise), fill=GOLD + (int(255 * alpha),), width=3)
            continue
        l, t_, r, b = font.getbbox(text, direction="rtl")
        x, y = (W - (r - l)) / 2 - l, yc - (b + t_) / 2 + rise
        sd.text((x + 3, y + 5), text, font=font, fill=(0, 0, 0, int(200 * alpha)), direction="rtl")
        td.text((x, y), text, font=font, fill=color + (int(255 * alpha),), direction="rtl")
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    layer.alpha_composite(shadow)
    layer.alpha_composite(txt)


def caption_alpha(t_local, dur):
    a_in, a_out = ease_out((t_local - 0.35) / 0.7), 1 - ease((t_local - (dur - 0.55)) / 0.5)
    return max(0.0, min(a_in, a_out)), 26 * (1 - ease_out((t_local - 0.35) / 0.8))


def render(fi):
    t = fi / FPS
    F = _A["fonts"]
    frame = np.zeros((H, W, 3), np.float32)
    weight_total = 0.0
    shade_amount = 0.0
    overlays = []

    # intro backdrop, fades into the first scene
    intro_w = 1 - ease((t - (INTRO - XFADE)) / XFADE)
    if intro_w > 0:
        frame += _A["intro_bg"] * intro_w
        weight_total += intro_w
        txt_out = 1 - ease((t - (INTRO - XFADE - 0.6)) / 0.6)
        a = ease_out((t - 0.3) / 1.0) * txt_out
        rise = 30 * (1 - ease_out((t - 0.3) / 1.2))
        a2 = ease_out((t - 0.9) / 1.0) * txt_out
        overlays.append(([("עוגה ביתית", F["title"], CREAM, H * 0.45)], a, rise))
        overlays.append(([("—", None, None, H * 0.535),
                          ("נאפתה באהבה, במטבח של הבית", F["sub"], GOLD, H * 0.585)], a2, rise * 0.6))

    for i, (s0, s1) in enumerate(SPANS):
        if not (s0 <= t < s1):
            continue
        dur = s1 - s0
        w_in = ease((t - s0) / XFADE) if i > 0 else 1.0 - intro_w
        w_out = 1 - ease((t - (s1 - XFADE)) / XFADE) if i < len(SCENES) - 1 else 1.0
        w = min(w_in, w_out)
        if w <= 0:
            continue
        frame += scene_frame(i, t - s0, dur) * w
        weight_total += w
        cap = SCENES[i][6]
        if cap:
            a, rise = caption_alpha(t - s0, dur - XFADE * 0.5)
            overlays.append(([(cap, F["cap"], CREAM, H * 0.86)], a * w, rise))
            shade_amount = max(shade_amount, a * w)
        if i == len(SCENES) - 1:
            te = t - (s0 + SCENES[i][1])  # closing title after the scene's own time
            a = ease_out(te / 1.0)
            dark = 0.55 * ease(te / 1.2)
            frame *= 1 - dark
            overlays.append(([("בתיאבון!", F["end"], CREAM, H * 0.47)], a, 34 * (1 - ease_out(te / 1.2))))
            a2 = ease_out((te - 0.6) / 1.0)
            overlays.append(([("—", None, None, H * 0.56),
                              ("עוגה ביתית · נאפתה באהבה", F["sub"], GOLD, H * 0.61)], a2, 0))

    if weight_total > 0:
        frame /= max(weight_total, 1e-6)
    frame = frame * _A["vignette"]
    if shade_amount > 0:
        frame = frame * (1 - (1 - _A["bottom_shade"]) * shade_amount)
    # fade from / to black
    frame *= ease(t / 0.6) * (1 - ease((t - (TOTAL - 0.9)) / 0.9))

    img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8)).convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_particles(layer, t, 0.85)
    for lines, a, rise in overlays:
        text_block(layer, lines, a, rise)
    img.alpha_composite(layer)
    return img.convert("RGB").tobytes()


# ---------------------------------------------------------------- music
def make_music(path, seconds, sr=44100):
    n = int(seconds * sr)
    out = np.zeros(n + sr * 4)
    bpm = 76
    beat = 60 / bpm

    def note_hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    def piano(m, dur, vel):
        L = int((dur + 2.5) * sr)
        tt = np.arange(L) / sr
        f = note_hz(m)
        sig = np.zeros(L)
        for k, amp in enumerate([1, .45, .22, .12, .06], start=1):
            sig += amp * np.sin(2 * np.pi * f * k * tt * (1 + 0.0004 * k)) * np.exp(-tt * (1.6 + 0.9 * k))
        att = np.minimum(1, tt / 0.006)
        return sig * att * vel

    def pad(ms, dur):
        L = int(dur * sr)
        tt = np.arange(L) / sr
        env = np.minimum(1, tt / 1.2) * np.minimum(1, (dur - tt) / 1.2)
        sig = sum(np.sin(2 * np.pi * note_hz(m) * tt) + 0.5 * np.sin(2 * np.pi * note_hz(m) * 1.003 * tt) for m in ms)
        return sig * env * 0.035

    def add(sig, at):
        i = int(at * sr)
        j = min(len(out), i + len(sig))
        out[i:j] += sig[: j - i]

    # Fmaj7 – Em7 – Dm7 – Cmaj7/G   (gentle, warm progression in C)
    chords = [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [43, 55, 59, 64]]
    melody = [[76, None, 74, 72], [71, None, 72, 74], [72, None, 69, 72], [71, None, None, 67]]
    bar = 4 * beat
    t, b = 0.0, 0
    while t < seconds:
        ch, mel = chords[b % 4], melody[b % 4]
        add(pad([m + 12 for m in ch[1:]], bar + 1.2), t)
        add(piano(ch[0] - 12, bar, 0.30), t)
        for k, m in enumerate([ch[0], ch[1], ch[2], ch[3], ch[2], ch[1], ch[2], ch[3]]):
            add(piano(m + 12, beat, 0.11), t + k * beat / 2)
        if b >= 1:
            for k, m in enumerate(mel):
                if m:
                    add(piano(m + 12, beat * 2, 0.16), t + k * beat)
        t += bar
        b += 1

    # simple FFT reverb: exponentially decaying noise impulse response
    rng = np.random.default_rng(1)
    ir_len = int(2.2 * sr)
    ir = rng.standard_normal(ir_len) * np.exp(-np.arange(ir_len) / sr * 3.2)
    ir[0] = 0
    size = 1 << int(math.ceil(math.log2(len(out) + ir_len)))
    wet = np.fft.irfft(np.fft.rfft(out, size) * np.fft.rfft(ir, size), size)[: len(out)]
    mix = out + 0.06 * wet
    mix = mix[:n]
    tt = np.arange(n) / sr
    mix *= np.minimum(1, tt / 1.0) * np.minimum(1, (seconds - tt) / 2.5)
    mix = mix / np.max(np.abs(mix)) * 0.8
    # stereo: tiny delay on the right channel for width
    d = int(0.012 * sr)
    right = np.concatenate([np.zeros(d), mix[:-d]])
    st = np.stack([mix, 0.85 * right + 0.15 * mix], axis=1)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((st * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- main
def main():
    photo_dir, out = sys.argv[1], sys.argv[2]
    audio = os.path.splitext(out)[0] + "_music.wav"
    make_music(audio, TOTAL)
    print(f"duration {TOTAL:.1f}s, {N_FRAMES} frames", flush=True)
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", audio,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out,
    ], stdin=subprocess.PIPE)
    with Pool(os.cpu_count(), initializer=load_assets, initargs=(photo_dir,)) as pool:
        for k, buf in enumerate(pool.imap(render, range(N_FRAMES), chunksize=4)):
            ff.stdin.write(buf)
            if k % 150 == 0:
                print(f"frame {k}/{N_FRAMES}", flush=True)
    ff.stdin.close()
    ff.wait()
    os.remove(audio)


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "--still":
        # preview: --still PHOTO_DIR OUT_DIR t1 t2 ...
        load_assets(sys.argv[2])
        for ts in sys.argv[4:]:
            fi = int(float(ts) * FPS)
            Image.frombytes("RGB", (W, H), render(fi)).save(os.path.join(sys.argv[3], f"still_{ts}.jpg"), quality=85)
    else:
        main()
