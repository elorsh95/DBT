"""Deterministic renderer for index.html: every frame is seek(t) + a screenshot, streamed into ffmpeg.
Settings (size, length, fps, loop) are read from window.CONFIG in index.html.

  python render.py check [FPS]           automatic review, sampled at FPS (default 10): page errors, text cut by the frame,
                                         text ink outside the safe area, words touching, hyphens between Hebrew words,
                                         labels too short to read, frozen stretches, frames that depend on the previous one.
                                         A word may leave the frame or the safe area for under 0.2 s (a slam), not at its
                                         last frame. Text drawn inside a canvas is not seen: check it on the stills.
  python render.py stills T1 T2 ...      stills/t-XX.XXX.png (full size) + stills/sheet.jpg (all of them on one image)
  python render.py strip A B [FPS]       contact sheets of every 1/FPS s in [A, B) (default 10 fps): stills/strip-A-B-N.jpg
  python render.py preview               out/preview.mp4: half size, 30 fps, no sub-frames, with sound
  python render.py full                  out/final.mp4: CONFIG size (or SCALE), CONFIG.FPS, motion blur, with sound
  python render.py flashcheck            mean brightness of every frame: jumps over 2% are flashes, more than 3 in a second fails
  python render.py gif [start=S] [len=L] [width=W] [fps=F] [colors=N] [soft]
                                         out/final.gif (or out/preview.gif when there is no final). Defaults for a web page:
                                         a 4 s segment from 0, 360 px wide (400 for square), 12 fps, 64 colours, target 1.2 MB.
                                         soft = a light blur before the palette (smaller file)

Numbers the scene wants to report (e.g. when growth ends) go in window.REPORT (core.js: report(key, value)).
check, stills and flashcheck print them. console.warn is for real problems only: check counts it as one.

Env: PAGE=compare.html renders another page of the project (stills of a reference page).
     SUB sub-frames per frame for motion blur in full: 4 (default), 8 for particles and neon (styles 03, 08)
     SCALE=0.5 renders full at half size (still with motion blur) | WORKERS=N parallel browsers
     T0 / T1 render only part of the timeline | NOAUDIO=1 silent video"""
import base64, io, json, os, re, shutil, subprocess, sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / os.environ.get("PAGE", "index.html")   # PAGE=compare.html: stills of another page in the project
OUT, STILLS = ROOT / "out", ROOT / "stills"
for _s in (sys.stdout, sys.stderr):   # Hebrew in messages must not crash a Windows console
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg not found. Install it (see references/setup.md) or run: pip install imageio-ffmpeg")


FF = find_ffmpeg()


def open_page(p, scale, sub=1, fps=None):
    """opens index.html at the given capture scale. window.RENDER tells core.js the shutter setup (for tf mb blur)."""
    from playwright.sync_api import Error
    b = p.chromium.launch(args=["--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none",
                                "--allow-file-access-from-files", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 400, "height": 400}, device_scale_factor=scale)
    pg.add_init_script(f"window.RENDER = {{sub: {int(sub)}, fps: {json.dumps(fps)}}};")
    errors = []
    pg.on("console", lambda m: (errors.append(m.text), print("console:", m.text)) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: (errors.append(str(e)), print("PAGEERROR:", e)))
    pg.goto(PAGE.as_uri())
    try:
        pg.evaluate("window.ready")
    except Error as e:
        sys.exit(f"the page did not load: {e}")
    cfg = pg.evaluate("window.CONFIG")
    pg.set_viewport_size({"width": int(cfg["W"]), "height": int(cfg["H"])})
    pg.errors, pg.scale = errors, scale
    return b, pg, pg.context.new_cdp_session(pg), cfg


def shot(pg, cdp, cfg):
    return base64.b64decode(cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True,
        "clip": {"x": 0, "y": 0, "width": cfg["W"], "height": cfg["H"], "scale": pg.scale}})["data"])


def grab(pg, cdp, cfg, t):
    pg.evaluate(f"seek({t!r})")
    return shot(pg, cdp, cfg)


def print_report(pg):
    """window.REPORT: numbers the scene reports on purpose (build time or later), printed as key: value"""
    rep = pg.evaluate("window.REPORT || {}") or {}
    for k, v in rep.items():
        print(f"report {k}: {json.dumps(v, ensure_ascii=False)}")


def sheet(paths, labels, out, cols, tw, gap=6):
    from PIL import Image, ImageDraw
    im0 = Image.open(paths[0]); th = round(tw * im0.height / im0.width)
    rows = (len(paths) + cols - 1) // cols
    sh = Image.new("RGB", (cols * (tw + gap), rows * (th + 22)), "white"); d = ImageDraw.Draw(sh)
    for k, (pth, lab) in enumerate(zip(paths, labels)):
        im = Image.open(pth).convert("RGB").resize((tw, th), Image.LANCZOS)
        x, y = (k % cols) * (tw + gap), (k // cols) * (th + 22)
        sh.paste(im, (x, y + 22)); d.text((x + 4, y + 5), lab, fill="black")
    sh.save(out, quality=88)


# ---------------------------------------------------------------- video
def sub_time(i, sub, fps, dur, loop):
    f, k = divmod(i, sub)
    t = (f + ((k + 0.5) / sub - 0.5) * 0.5) / fps if sub > 1 else f / fps   # 180-degree shutter centred on the frame
    return t % dur if loop else min(dur, max(0.0, t))


def worker(job):
    """one browser renders frames [f0, f1): sub-frames stream into ffmpeg, tmix averages them, select keeps one per frame"""
    wi, f0, f1, scale, fps, sub, preview, seg_dir = job
    from playwright.sync_api import sync_playwright
    seg = Path(seg_dir) / f"seg{wi:02d}.mp4"
    vf = (f"tmix=frames={sub}:weights={' '.join(['1'] * sub)},select=not(mod(n-{sub - 1}\\,{sub})),setpts=N/{fps}/TB,"
          if sub > 1 else f"setpts=N/{fps}/TB,") + "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"
    with sync_playwright() as p:
        b, pg, cdp, cfg = open_page(p, scale, sub, fps)
        ff = subprocess.Popen([FF, "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(fps * sub), "-c:v", "png",
                               "-i", "-", "-vf", vf, "-r", str(fps), "-c:v", "libx264", "-crf", "20" if preview else "16",
                               "-preset", "veryfast" if preview else "medium", "-tune", "animation", str(seg)], stdin=subprocess.PIPE)
        for i in range(f0 * sub, f1 * sub):
            ff.stdin.write(grab(pg, cdp, cfg, sub_time(i, sub, fps, cfg["DUR"], cfg.get("loop"))))
        b.close()
    ff.stdin.close(); ff.wait()
    if ff.returncode:
        raise RuntimeError(f"ffmpeg failed on chunk {wi}")
    return str(seg)


def make_audio(cfg, cues):
    """out/audio.wav from the sound cues and the optional music. Returns the path or None."""
    if os.environ.get("NOAUDIO") or (not cues and not cfg.get("music")):
        return None
    try:
        import audio
        return audio.build(ROOT, cfg, cues)
    except Exception as e:
        print("audio skipped:", e)
        return None


def render_video(preview):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b, pg, cdp, cfg = open_page(p, 0.25)
        cues = pg.evaluate("window.SFX")
        b.close()
    OUT.mkdir(exist_ok=True)
    (OUT / "cues.json").write_text(json.dumps({"config": cfg, "cues": cues}, ensure_ascii=False, indent=1), encoding="utf-8")
    wav = make_audio(cfg, cues)

    scale = float(os.environ.get("SCALE", 0.5 if preview else 1.0))
    fps = 30 if preview else int(cfg["FPS"])
    sub = 1 if preview else max(1, int(os.environ.get("SUB", "4")))
    dur = float(cfg["DUR"])
    t0, t1 = float(os.environ.get("T0", 0)), float(os.environ.get("T1", dur))
    fa, fb = int(round(t0 * fps)), int(round(t1 * fps)); nf = fb - fa
    workers = max(1, min(int(os.environ.get("WORKERS", max(1, min(6, cpu_count() - 1)))), nf))
    seg_dir = OUT / "seg"; shutil.rmtree(seg_dir, ignore_errors=True); seg_dir.mkdir(parents=True)
    chunk = (nf + workers - 1) // workers
    jobs = [(k, fa + k * chunk, min(fb, fa + (k + 1) * chunk), scale, fps, sub, preview, str(seg_dir))
            for k in range(workers) if k * chunk < nf]
    print(f"rendering {nf} frames ({fps} fps, {sub} sub-frames, scale {scale}) with {len(jobs)} workers")
    try:
        with Pool(len(jobs)) as pool:
            segs = pool.map(worker, jobs)
        lst = seg_dir / "list.txt"
        lst.write_text("".join(f"file '{Path(s).as_posix()}'\n" for s in segs), encoding="utf-8")
        out = OUT / ("preview.mp4" if preview else "final.mp4")
        cmd = [FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]   # chunks joined by stream copy
        if wav:
            cmd += ["-ss", str(t0), "-t", str(t1 - t0), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "copy", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(seg_dir, ignore_errors=True)
    print("video", out, "with sound" if wav else "silent")


# ---------------------------------------------------------------- check
TEXT_JS = r"""() => {
  const eff = el => { if (getComputedStyle(el).visibility !== 'visible') return 0; let o = 1;
    for (let e = el; e && e !== document.body; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.display === 'none') return 0; o *= +cs.opacity; }
    return o; };
  const out = [];
  document.querySelectorAll('.tx').forEach((e, i) => {
    const s = e.textContent.trim(); if (!s || eff(e) <= 0.5) return;
    const r = e.getBoundingClientRect(); out.push({ i, s: s.slice(0, 30), x0: r.left, y0: r.top, x1: r.right, y1: r.bottom });
  });
  return out;
}"""
# 'none' hides every text box, 'solo' shows only box i: the difference against 'none' is that box's ink, in pixels
MASK_JS = r"""([mode, i]) => {
  let st = document.getElementById('__mask');
  if (!st) { st = document.createElement('style'); st.id = '__mask'; document.head.appendChild(st); }
  document.querySelectorAll('.tx.__solo').forEach(e => e.classList.remove('__solo'));
  if (mode === 'all') { st.textContent = ''; return; }
  st.textContent = '.tx{visibility:hidden!important}.tx.__solo{visibility:visible!important}';
  if (mode === 'solo') document.querySelectorAll('.tx')[i].classList.add('__solo');
}"""


def safe_rect(W, H):
    """(x0, y0, x1, y1) the text must stay inside, plus the Instagram button column for tall frames"""
    if H / W > 1.6:   # Reels / Stories, measured on 1080x1920 and scaled to the actual width
        f = W / 1080
        return (80 * f, 250 * f, W - 80 * f, H - 350 * f), (W - 140 * f, H / 2, W, H)
    m = 0.06 * min(W, H)
    return (m, m, W - m, H - m), None


def check(fps):
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageChops, ImageFilter, ImageStat
    problems, gap_px = [], 6
    with sync_playwright() as p:
        b, pg, cdp, cfg = open_page(p, 0.5)
        W, H, dur, loop = cfg["W"], cfg["H"], float(cfg["DUR"]), bool(cfg.get("loop"))
        k = pg.scale; (sx0, sy0, sx1, sy1), btn = safe_rect(W, H)
        texts = pg.evaluate("[...document.querySelectorAll('.tx, text')].map(e => e.textContent)") or []
        for s in set(texts):
            if re.search(r"[\u0590-\u05FF]-[\u0590-\u05FF]", s):
                problems.append(f"hyphen between Hebrew words: {s.strip()[:40]}")
            if re.search(r"[\u2013\u2014]", s):
                problems.append(f"long dash in on-screen text: {s.strip()[:40]}")
        img = lambda png: Image.open(io.BytesIO(png)).convert("RGB")
        ink = lambda a, b_: ImageChops.difference(a, b_).convert("L").point(lambda v: 255 if v > 40 else 0)

        def outside(mask):   # which sides of the safe area the ink crosses ('' = none)
            Wk, Hk = mask.size
            boxes = {"top": (0, 0, Wk, sy0 * k), "bottom": (0, sy1 * k, Wk, Hk), "left": (0, 0, sx0 * k, Hk),
                     "right": (sx1 * k, 0, Wk, Hk)}
            if btn: boxes["Instagram buttons (lower right)"] = tuple(v * k for v in btn)
            return ", ".join(n for n, bx in boxes.items() if mask.crop(tuple(int(v) for v in bx)).getbbox())

        n = int(round(dur * fps)); last = None; moving = []
        vis, clip, unsafe, touch, sides = {}, {}, {}, {}, {}
        for step in range(n + (0 if loop else 1)):
            t = min(dur, step / fps)
            full = img(grab(pg, cdp, cfg, t))
            els = pg.evaluate(TEXT_JS)
            for e in els:
                vis.setdefault(e["i"], [e["s"], []])[1].append(t)
                inside = e["x1"] > 0 and e["y1"] > 0 and e["x0"] < W and e["y0"] < H   # fully outside = not seen, fine
                if inside and (e["x0"] < -2 or e["y0"] < -2 or e["x1"] > W + 2 or e["y1"] > H + 2):
                    clip.setdefault(e["i"], []).append(t)
            els = [e for e in els if e["x1"] > 0 and e["y1"] > 0 and e["x0"] < W and e["y0"] < H]
            cand = [e for e in els if e["x0"] < sx0 or e["y0"] < sy0 or e["x1"] > sx1 or e["y1"] > sy1
                    or (btn and e["x1"] > btn[0] and e["y1"] > btn[1])]
            near = [(a, c) for ai, a in enumerate(els) for c in els[ai + 1:]
                    if min(a["x1"], c["x1"]) - max(a["x0"], c["x0"]) > -16 and min(a["y1"], c["y1"]) - max(a["y0"], c["y0"]) > -16]
            need = {e["i"] for e in cand} | {e["i"] for pr in near for e in pr}
            if need:
                pg.evaluate(MASK_JS, ["none", -1]); none = img(shot(pg, cdp, cfg)); masks = {}
                for i in need:
                    pg.evaluate(MASK_JS, ["solo", i]); masks[i] = ink(img(shot(pg, cdp, cfg)), none)
                pg.evaluate(MASK_JS, ["all", -1])
                for e in cand:
                    side = outside(masks[e["i"]])
                    if side:
                        unsafe.setdefault(e["i"], []).append(t); sides.setdefault(e["i"], set()).update(side.split(", "))
                for a, c in near:   # two words need a gap of at least 12% of the smaller one's size (6 px minimum)
                    gap = max(gap_px, 0.12 * min(a["y1"] - a["y0"], c["y1"] - c["y0"]))
                    grow = ImageFilter.MaxFilter(2 * max(1, round(gap * k)) + 1)
                    if ImageChops.multiply(masks[a["i"]].filter(grow), masks[c["i"]]).getbbox():
                        touch.setdefault((a["i"], c["i"]), [f'"{a["s"]}" / "{c["s"]}"', []])[1].append(t)
            small = full.convert("L").resize((90, round(90 * H / W)))
            if last is not None:
                moving.append((t, ImageStat.Stat(ImageChops.difference(small, last)).mean[0] > 0.12))
            last = small
        for t in (0.23 * dur, 0.51 * dur, 0.77 * dur):   # seek(t) must not depend on what was shown before
            a = img(grab(pg, cdp, cfg, t)); grab(pg, cdp, cfg, dur); grab(pg, cdp, cfg, 0.0); c = img(grab(pg, cdp, cfg, t))
            if ImageStat.Stat(ImageChops.difference(a, c)).mean[0] > 0.05:
                problems.append(f"frame at {t:.2f}s changes depending on what was shown before: something keeps state between frames")
        problems += pg.errors
        report = pg.evaluate("window.REPORT || {}") or {}
        b.close()

    span = lambda ts: f"{ts[0]:.2f}s" + (f"..{ts[-1]:.2f}s" if len(ts) > 1 else "")
    runs = lambda ts: [r for r in _runs(ts, 1.5 / fps)]
    # a slam or a slide from off screen may poke out for a moment; 0.2 s or more, or at the word's last frame, is a problem
    for what, bad in (("text cut by the frame", clip), ("text outside the safe area", unsafe)):
        for i, ts in bad.items():
            s, seen = vis[i]
            where = f" ({', '.join(sorted(sides[i]))})" if bad is unsafe else ""
            for r in runs(ts):
                if r[-1] - r[0] >= 0.2 - 1e-6 or r[-1] == seen[-1]:
                    problems.append(f'{what}{where}: "{s}" at {span(r)}')
    for pair, ts in touch.values():
        for r in runs(ts):
            problems.append(f"words touching or almost touching: {pair} at {span(r)}")
    for i, (s, seen) in vis.items():   # reading time
        for r in runs(seen):
            on = r[-1] - r[0] + 1 / fps
            at_end = not loop and r[-1] >= dur - 1e-6
            if at_end and on < 1.5 - 1e-6:
                problems.append(f'final text "{s}" is on screen only {on:.1f}s before the end (hold it at least 1.5s)')
            elif not at_end and " " in s and re.search(r"[\u0590-\u05FF]", s) and on < 1.3 - 1e-6:   # Hebrew phrases; mono tags are decoration
                problems.append(f'label "{s}" is on screen only {on:.1f}s (at least 1.3s to read it)')
    frozen = []
    hold_from = dur - float(cfg.get("hold") or 0)   # CONFIG.hold: seconds at the end that may stand still (a logo lockup)
    for t, mv in moving:
        if not mv and not (not loop and t > hold_from + 1e-6):
            frozen.append(t)
    for r in runs(frozen):
        if r[-1] - r[0] + 1 / fps > 0.34:
            problems.append(f"nearly frozen picture {r[0] - 1 / fps:.2f}s..{r[-1]:.2f}s (keep something moving)")
    print(f"config: {cfg['W']}x{cfg['H']}, {cfg['DUR']}s, loop={cfg.get('loop')}")
    for k, v in report.items():
        print(f"report {k}: {json.dumps(v, ensure_ascii=False)}")
    print("\n".join(problems) if problems else "check passed: no problems found")


def _runs(ts, gap):
    out, cur = [], []
    for t in ts:
        if cur and t - cur[-1] > gap:
            out.append(cur); cur = []
        cur.append(t)
    if cur: out.append(cur)
    return out


# ---------------------------------------------------------------- flashes
def flashcheck():
    """every displayed frame at CONFIG.FPS, small: mean brightness 0..100%. A rise of more than 2 points in one frame is a
    flash; more than 3 flashes inside any 1 s window fails (the limit in the styles)."""
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageStat
    with sync_playwright() as p:
        b, pg, cdp, cfg = open_page(p, 0.15)
        fps, dur = int(cfg["FPS"]), float(cfg["DUR"])
        lum = []
        for f in range(int(round(dur * fps))):
            im = Image.open(io.BytesIO(grab(pg, cdp, cfg, f / fps))).convert("L")
            lum.append(ImageStat.Stat(im).mean[0] / 2.55)
        print_report(pg)
        b.close()
    flashes = [(f / fps, lum[f] - lum[f - 1]) for f in range(1, len(lum)) if lum[f] - lum[f - 1] > 2.0]
    print(f"brightness: min {min(lum):.1f}%, max {max(lum):.1f}%, {len(flashes)} flash frame(s)")
    for t, d in flashes:
        print(f"  flash at {t:.3f}s (+{d:.1f} points)")
    bad = sorted({round(t0, 3) for t0, _ in flashes if sum(1 for t, _ in flashes if t0 <= t < t0 + 1.0) > 3})
    if bad:
        print("FAIL: more than 3 flashes within 1 s, starting at " + ", ".join(f"{t:.2f}s" for t in bad))
    else:
        print("flashcheck passed: at most 3 flashes in any second")


# ---------------------------------------------------------------- gif
def gif(args):
    """a short, light GIF for a web page, cut from the rendered MP4"""
    o = {"start": 0.0, "len": 4.0, "width": 0, "fps": 12, "colors": 64}
    soft = False
    for a in args:
        if a == "soft": soft = True; continue
        k, _, v = a.partition("=")
        if k not in o: sys.exit(f"unknown gif option '{a}'. Options: start= len= width= fps= colors= soft")
        o[k] = float(v)
    src = OUT / "final.mp4" if (OUT / "final.mp4").exists() else OUT / "preview.mp4"
    if not src.exists():
        sys.exit("render a video first (preview or full)")
    info = subprocess.run([FF, "-hide_banner", "-i", str(src)], capture_output=True, text=True).stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    vw, vh = (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)
    width = int(o["width"]) or (400 if abs(vw - vh) < 8 else 360)
    out = src.with_suffix(".gif")
    pre = f"fps={int(o['fps'])},scale={width}:-2:flags=lanczos" + (",gblur=sigma=0.6" if soft else "")
    vf = (f"{pre},split[a][b];[a]palettegen=max_colors={int(o['colors'])}:stats_mode=diff[p];"
          f"[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    subprocess.run([FF, "-y", "-v", "error", "-ss", str(o["start"]), "-t", str(o["len"]), "-i", str(src),
                    "-vf", vf, "-loop", "0", str(out)], check=True)
    mb = out.stat().st_size / 1e6
    print(f"gif {out} {width}px, {int(o['fps'])} fps, {int(o['colors'])} colours, {o['len']:g}s: {mb:.2f} MB")
    if mb > 1.2:
        print("over 1.2 MB. Try in this order: a shorter segment (len=3), colors=48 soft, or render a clean version for the "
              "GIF without grain and without camera moves (grain and constant motion are what makes a GIF heavy).")


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    mode = sys.argv[1]
    STILLS.mkdir(exist_ok=True)
    if mode == "stills":
        from playwright.sync_api import sync_playwright
        ts = [float(x) for x in sys.argv[2:]]
        with sync_playwright() as p:
            b, pg, cdp, cfg = open_page(p, 1.0)
            outs = []
            for t in ts:
                o = STILLS / f"t-{t:06.3f}.png"; k = 2
                while o in outs:   # the same time twice keeps both files
                    o = STILLS / f"t-{t:06.3f}-{k}.png"; k += 1
                o.write_bytes(grab(pg, cdp, cfg, t)); outs.append(o)
            print_report(pg)
            b.close()
        sheet(outs, [f"{t:.3f}s" for t in ts], STILLS / "sheet.jpg", cols=min(6, len(outs)), tw=300)
        print("stills", *[o.name for o in outs], "+ sheet", STILLS / "sheet.jpg")
    elif mode == "strip":
        from playwright.sync_api import sync_playwright
        a, bnd = float(sys.argv[2]), float(sys.argv[3]); fps = float(sys.argv[4]) if len(sys.argv) > 4 else 10
        tmp = STILLS / "_strip"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
        ts = [a + k / fps for k in range(int(round((bnd - a) * fps)))]
        with sync_playwright() as p:
            b, pg, cdp, cfg = open_page(p, 0.3)
            outs = []
            for k, t in enumerate(ts):
                o = tmp / f"{k:04d}.png"; o.write_bytes(grab(pg, cdp, cfg, t)); outs.append(o)
            b.close()
        per = 60 if cfg["H"] > cfg["W"] else 40
        for s in range(0, len(outs), per):
            out = STILLS / f"strip-{a:05.2f}-{bnd:05.2f}-{s // per}.jpg"
            sheet(outs[s:s + per], [f"{t:.2f}" for t in ts[s:s + per]], out, cols=10, tw=162 if cfg["H"] > cfg["W"] else 216)
            print("strip", out)
        shutil.rmtree(tmp, ignore_errors=True)
    elif mode == "check":
        check(float(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif mode in ("preview", "full"):
        render_video(mode == "preview")
    elif mode == "flashcheck":
        flashcheck()
    elif mode == "gif":
        gif(sys.argv[2:])
    else:
        sys.exit(__doc__)
