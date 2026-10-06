'use strict';
// =====================================================================================
// core.js: a tiny deterministic motion engine for code-rendered animation.
// Every style is a pure function of t: no CSS transitions, no timers, no state between frames.
// Scenes register with scene(); the engine builds them once, then seek(t) drives everything.
//
// Settings come from window.CONFIG (set in index.html BEFORE this file loads):
//   W, H      canvas size in px            (default 1080 x 1920)
//   DUR       length in seconds            (default 8)
//   FPS       final frame rate             (default 60)
//   bg        stage colour                 (default '#0E0E10')
//   loop      true = seamless loop: t wraps at DUR, track() and vis() close the loop
//   bpm       beat grid tempo              (default 120), beat0 = time of beat 0 in seconds
//   palette   colours merged into C        (optional)
//   music     {file, start, gain} optional, read by audio.py (file sits in the project folder)
//
// API (all times in seconds, global t):
//   math     clamp(x,a,b) | lerp(a,b,k) | f2(v) 2-decimal string
//   time     S(tau,wn,z) spring step | track(v0, [[t, v, wn?, z?], ...]) value retargeted many times
//            sp(t,a,wn,z) spring from a | vis(t,a,b) fade-in at a, fade-out at b | seg(t,a,b) 0..1 ramp
//            E.o3 / E.expo / E.io3 ... easings (only for things that are not springs)
//            slam(t,t0,from) scale slam | rise(t,t0,dist) Hebrew-safe word entrance | fall(t,t0,v0,g)
//            typed(t,t0,n,cps) chars visible | shake(t, [[t0,amp],...]) camera shake -> [dx,dy,rot]
//            hash(i) 0..1 | rng(seed) build-time random stream | vnoise(x,seed) smooth noise -1..1
//            vel(f, t) velocity of a closed-form f (number or array) in px per frame at CONFIG.FPS
//            beat(n) time of beat n on the CONFIG grid
//   DOM      div, rect(x,y,w,h), box(cx,cy,w,h), grp(x,y) zero-size anchor, canvas2d(parent)
//            txt(parent, s, {x,y,size,font,weight,wdth,color,align,ls,lh,dir,dy,css}) returns the anchor, .inner = text box
//            letters(...) per-letter spans in .spans | row(parent, words, {...}) Hebrew words laid out right to left
//            measure(s,o) {w,h} | fit(s,o,width,max) font size that fills width
//            tf(el, {x,y,z,s,sx,sy,r,rx,ry,skx,sky,o,blur,mb}) one call sets transform, opacity, blur, visibility
//            mb: [vx, vy] screen velocity in px per frame (from vel) adds a directional blur to very fast moves
//            on(el, bool) show or hide | svgEl(tag,parent,attrs) | svgBox(parent,x,y,w,h)
//            icon(parent, P.check, x,y,size,color) | cursor(parent, size, fill, stroke)
//   scenes   scene(id, a, b, {bg}, (root, ctx) => { build once; return t => { pure function of t } })
//            instance(id, parent) a second live copy of a scene | sfx(t, kind, gain) sound cue (build time only)
//   report   report(key, value) puts a number in window.REPORT; render.py check / stills / flashcheck print it.
//            Use it for measurements (when growth ends, the highest point of a field). console.warn is for real problems.
//   palette  C.INK C.INK2 C.PAPER C.WHITE C.RED C.BLUE C.YELLOW C.GREY (override with CONFIG.palette)
//   fonts    F.D (Noto Sans Hebrew) F.RUBIK F.HEEBO F.LAT (Archivo) F.MONO (JetBrains Mono, Latin only) F.HAND (Amatic SC)
// =====================================================================================
const CFG = Object.assign({ W: 1080, H: 1920, DUR: 8, FPS: 60, bg: '#0E0E10', loop: false, bpm: 120, beat0: 0 }, window.CONFIG || {});
window.CONFIG = CFG;
const W = CFG.W, H = CFG.H, DUR = CFG.DUR, FPS = CFG.FPS;

// ---------- palette + type ----------
const C = Object.assign({
  INK: '#0E0E10', INK2: '#1B1B1F', PAPER: '#EFEAE2', WHITE: '#F4F1EC',
  RED: '#E54136', BLUE: '#2E3BFF', YELLOW: '#F7C22F', GREY: '#8C8882',
}, CFG.palette || {});
const F = {
  D: "'Noto Sans Hebrew'",   // hero Hebrew, weight 900, font-stretch 62.5%..100% (animatable width)
  RUBIK: 'Rubik',            // Hebrew UI text and labels, 400..700
  HEEBO: 'Heebo',            // Hebrew UI text, alternative
  LAT: 'Archivo',            // Latin display, 900, font-stretch 62%..125%
  MONO: "'JetBrains Mono'",  // tiny technical labels in English. Has no Hebrew glyphs.
  HAND: "'Amatic SC'",       // hand lettering (doodle speech bubbles), Hebrew and Latin, 400/700
};

// ---------- math ----------
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const lerp = (a, b, k) => a + (b - a) * k;
const f2 = v => (+v).toFixed(2);
const seg = (t, a, b) => clamp((t - a) / (b - a), 0, 1);
const beat = n => CFG.beat0 + n * 60 / CFG.bpm;
// how render.py is capturing right now: sub-frames per frame and capture fps (set before the page loads)
const RND = Object.assign({ sub: 1, fps: null }, window.RENDER || {});
// velocity of a closed-form function of t, in px per frame at CONFIG.FPS (for tf mb). Still a pure function of t.
const vel = (f, t) => { const a = f(t), b = f(t - 1 / FPS); return Array.isArray(a) ? a.map((v, i) => v - b[i]) : a - b; };
const E = {
  o2: x => 1 - (1 - x) ** 2, o3: x => 1 - (1 - x) ** 3, o4: x => 1 - (1 - x) ** 4, o5: x => 1 - (1 - x) ** 5,
  i2: x => x * x, i3: x => x * x * x, io3: x => x < .5 ? 4 * x ** 3 : 1 - (-2 * x + 2) ** 3 / 2,
  expo: x => x >= 1 ? 1 : 1 - Math.pow(2, -10 * x),
  smooth: x => x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x),
};

// closed-form unit step response of a damped spring: 0 before tau = 0, settles at 1.
// wn = stiffness (rad/s, 8 slow .. 40 snappy), z = damping (1 = no overshoot, 0.7 = a small one)
function S(tau, wn, z) {
  if (tau <= 0) return 0;
  if (z >= 1) return 1 - Math.exp(-wn * tau) * (1 + wn * tau);
  const wd = wn * Math.sqrt(1 - z * z);
  return 1 - Math.exp(-z * wn * tau) * (Math.cos(wd * tau) + (z * wn / wd) * Math.sin(wd * tau));
}
// in loop mode a spring started in the previous cycle is still settling at the start of this one
const SL = (tau, wn, z) => CFG.loop ? S(tau, wn, z) + S(tau + DUR, wn, z) - 1 : S(tau, wn, z);

// a value retargeted many times = v0 + one spring per change. keys: [sec, value, wn?, z?]; value may be an array
// (null entries in an array keep the previous value). In loop mode the last value must equal v0.
function track(v0, keys, wn = 13, z = 0.82) {
  keys = keys.slice().sort((a, b) => a[0] - b[0]);
  const vec = Array.isArray(v0), n = vec ? v0.length : 1;
  let prev = vec ? v0 : [v0];
  const ks = keys.map(k => {
    const v = vec ? k[1].map((x, i) => x ?? prev[i]) : [k[1]];
    const d = v.map((x, i) => x - prev[i]); prev = v;
    return { t: k[0], d, w: k[2] || wn, z: k[3] || z };
  });
  if (CFG.loop && prev.some((x, i) => Math.abs(x - (vec ? v0[i] : v0)) > 1e-9)) console.warn('track does not close the loop', v0, prev);
  return t => {
    const out = vec ? v0.slice() : [v0];
    for (const k of ks) {
      const s = SL(t - k.t, k.w, k.z);
      if (s === 0) continue;
      for (let i = 0; i < n; i++) out[i] += k.d[i] * s;
    }
    return vec ? out : out[0];
  };
}
const sp = (t, a, wn = 16, z = 1) => S(t - a, wn, z);
// visibility window: springs in at a, out at b (0..1). In loop mode a window may cross the seam.
function vis(t, a, b = 1e9, wi = 20, wo = 26) {
  const f = x => clamp(sp(x, a, wi) * (1 - sp(x, b, wo)), 0, 1);
  return CFG.loop ? Math.max(f(t), f(t - DUR), f(t + DUR)) : f(t);
}
const hash = i => { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
function rng(seed) {   // mulberry32: deterministic stream for build-time layout. Never call it inside seek.
  let a = seed >>> 0;
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function vnoise(x, seed = 0) {   // smooth 1D value noise in [-1, 1]
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
  return lerp(hash(i + seed * 97.3) * 2 - 1, hash(i + 1 + seed * 97.3) * 2 - 1, u);
}
// camera shake from impacts: hits = [[t0, amp px], ...] -> [dx, dy, rotDeg]
function shake(t, hits, freq = 26, decay = 9) {
  let x = 0, y = 0, r = 0;
  hits.forEach(([t0, amp], k) => {
    const u = t - t0; if (u < 0 || u > 1.2) return;
    const a = amp * Math.exp(-u * decay);
    x += a * vnoise(u * freq, 3 + k); y += a * vnoise(u * freq, 11 + k); r += a * 0.05 * vnoise(u * freq * 0.7, 19 + k);
  });
  return [x, y, r];
}
// kinetic type slam: scale `from` -> 1 on a fast underdamped spring (dips a little under 1, comes back); o = 0 before t0.
// Keep from <= 1.25 for words, and small enough that the biggest frame still fits the frame.
function slam(t, t0, from = 1.25, wn = 34, z = 0.6) {
  if (t < t0) return { s: from, o: 0 };
  return { s: 1 + (from - 1) * (1 - S(t - t0, wn, z)), o: 1 };
}
// Hebrew-safe word entrance: a short rise + 60 ms opacity ramp, no mask edge.
// (Hebrew letter tops or baselines seen through a mask edge read as dashes or as another word.)
function rise(t, t0, dist = 46, wn = 30, z = 0.78) {
  if (t < t0) return { o: 0, y: dist };
  return { o: clamp((t - t0) / 0.06, 0, 1), y: (1 - S(t - t0, wn, z)) * dist };
}
// ballistic fall after t0: y = v0*u + g*u^2/2
const fall = (t, t0, v0 = 0, g = 5200) => { const u = Math.max(0, t - t0); return v0 * u + 0.5 * g * u * u; };
// count of characters visible for a type-on starting at t0 (chars per second)
const typed = (t, t0, n, cps = 22) => clamp(Math.floor((t - t0) * cps + (t >= t0 ? 1 : 0)), 0, n);

// ---------- DOM ----------
const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
function div(parent, css = {}, cls = 'a') {
  const d = document.createElement('div'); d.className = cls; Object.assign(d.style, css);
  if (parent) parent.appendChild(d); return d;
}
// box by top-left
const rect = (parent, x, y, w, h, css = {}) => div(parent, Object.assign({ left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' }, css));
// box by centre
const box = (parent, cx, cy, w, h, css = {}) => rect(parent, cx - w / 2, cy - h / 2, w, h, css);
// zero-size anchor at (x, y); its transform scales/rotates around that point
function grp(parent, x = 0, y = 0) { return div(parent, { left: x + 'px', top: y + 'px' }, 'g'); }
// a 2D canvas placed at (x, y). Redraw it from t inside seek (clear first). Returns the 2D context (.canvas = element)
function canvas2d(parent, x = 0, y = 0, w = W, h = H) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  c.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px`;
  parent.appendChild(c); return c.getContext('2d');
}
function svgEl(tag, parent, attrs = {}) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e); return e;
}
// absolutely placed svg canvas: top-left (x, y), size w x h, user units = px
function svgBox(parent, x, y, w, h) {
  const s = svgEl('svg', parent, { width: w, height: h, viewBox: `0 0 ${w} ${h}` });
  s.style.cssText = `position:absolute;left:${x}px;top:${y}px;overflow:visible`; return s;
}
function fontCss(st, o) {
  st.fontFamily = o.font || F.D; st.fontSize = (o.size || 120) + 'px'; st.fontWeight = o.weight || 900;
  st.fontStretch = (o.wdth || 100) + '%'; st.color = o.color || C.WHITE; st.letterSpacing = (o.ls || 0) + 'em';
  st.lineHeight = o.lh || 1; st.direction = o.dir || 'rtl';
  if (o.css) Object.assign(st, o.css);
}
// text anchored at (o.x, o.y): align c = centred, r = right edge on x, l = left edge on x; vertically centred on y.
// returns the anchor group; .inner is the text node box
function txt(parent, s, o = {}) {
  const g = grp(parent, o.x || 0, o.y || 0);
  const d = div(g, {}, 'tx'); fontCss(d.style, o);
  const al = o.align || 'c';
  d.style.transform = `translate(${al === 'c' ? -50 : al === 'r' ? -100 : 0}%, ${o.dy ?? -50}%)`;
  d.textContent = s; g.inner = d; return g;
}
// same as txt, but every character is its own inline-block span (g.spans) for per-letter animation.
// Hebrew has no joining letters, so splitting is safe; keep the spans in reading order (the DOM stays RTL).
function letters(parent, s, o = {}) {
  const g = txt(parent, '', o);
  g.spans = [...s].map(ch => {
    const sp_ = document.createElement('span'); sp_.textContent = ch;
    sp_.style.display = 'inline-block'; sp_.style.whiteSpace = 'pre'; sp_.style.transformOrigin = o.origin || '50% 70%';
    g.inner.appendChild(sp_); return sp_;
  });
  return g;
}
// rendered size of a string (fonts are loaded before any scene builds)
function measure(s, o = {}) {
  const d = div(document.body, { position: 'absolute', left: '-9999px', top: '0', whiteSpace: 'nowrap' }, 'tx');
  fontCss(d.style, o); d.textContent = s; const r = d.getBoundingClientRect(); d.remove();
  return { w: r.width, h: r.height };
}
// font size at which s spans `width` px (capped at max)
const fit = (s, o, width, max = 2000) => Math.min(max, 100 * width / measure(s, Object.assign({}, o, { size: 100 })).w);
// a line of Hebrew words, each in its own anchor so each can enter on its own time.
// The FIRST word sits on the RIGHT (reading order). o: txt options + {x (centre of the line), y, gap}.
// returns [{g, w, cx}] in reading order.
function row(parent, words, o = {}) {
  const gap = o.gap ?? (o.size || 120) * 0.28;
  const ws = words.map(s => measure(s, o).w);
  let xr = (o.x || 0) + (ws.reduce((a, b) => a + b, 0) + gap * (words.length - 1)) / 2;
  return words.map((s, k) => {
    const cx = xr - ws[k] / 2; xr -= ws[k] + gap;
    return { g: txt(parent, s, Object.assign({}, o, { x: cx, align: 'c' })), w: ws[k], cx };
  });
}

// set transform / opacity / blur / visibility in one call. p: {x,y,z,s,sx,sy,r,rx,ry,skx,sky,o,blur}
function tf(el, p = {}) {
  const o = p.o ?? 1;
  if (o <= 0.003) { el.style.visibility = 'hidden'; return false; }
  el.style.visibility = 'inherit';
  el.style.opacity = o >= 0.999 ? '1' : o.toFixed(4);
  let s = '';
  if (p.x || p.y || p.z) s += `translate3d(${f2(p.x || 0)}px,${f2(p.y || 0)}px,${f2(p.z || 0)}px) `;
  if (p.rx) s += `rotateX(${f2(p.rx)}deg) `;
  if (p.ry) s += `rotateY(${f2(p.ry)}deg) `;
  if (p.r) s += `rotate(${f2(p.r)}deg) `;
  const sc = p.s ?? 1, sx = (p.sx ?? 1) * sc, sy = (p.sy ?? 1) * sc;
  if (sx !== 1 || sy !== 1) s += `scale(${sx.toFixed(4)},${sy.toFixed(4)}) `;
  if (p.skx) s += `skewX(${f2(p.skx)}deg) `;
  if (p.sky) s += `skewY(${f2(p.sky)}deg) `;
  el.style.transform = s || 'none';
  const fl = [];
  if (p.mb) { const u = mblur(el, p.mb[0] / Math.abs(sx || 1), p.mb[1] / Math.abs(sy || 1)); if (u) fl.push(u); }
  if (p.blur > 0.05) fl.push(`blur(${p.blur.toFixed(2)}px)`);
  el.style.filter = fl.length ? fl.join(' ') : 'none';
  return true;
}
// directional blur for very fast moves. The render averages sub-frames (true motion blur), but a move of many px per frame
// leaves separate ghost copies between sub-frames; this smear fills the gaps. It scales with the shutter the render uses:
// half a frame of travel, split over the sub-frames. vx, vy in the element's own px per frame (tf divides by its scale;
// divide by a parent camera zoom yourself). Only axis-aligned.
let MB_DEFS = null, MB_N = 0;
function mblur(el, vx, vy) {
  const shutter = 0.5 * (RND.fps ? FPS / RND.fps : 1) / Math.max(1, RND.sub);
  const bx = Math.abs(vx) * shutter * 0.35, by = Math.abs(vy) * shutter * 0.35;
  if (bx < 0.5 && by < 0.5) return null;
  if (!MB_DEFS) { const s = svgEl('svg', document.body, { width: 0, height: 0 }); s.style.position = 'absolute'; MB_DEFS = svgEl('defs', s); }
  if (!el._mb) {
    const f = svgEl('filter', MB_DEFS, { id: `mb${MB_N++}`, x: '-50%', y: '-50%', width: '200%', height: '200%', 'color-interpolation-filters': 'sRGB' });
    el._mb = { id: f.id, g: svgEl('feGaussianBlur', f, { stdDeviation: '0 0' }) };
  }
  el._mb.g.setAttribute('stdDeviation', `${bx.toFixed(2)} ${by.toFixed(2)}`);
  return `url(#${el._mb.id})`;
}
const on = (el, v) => { el.style.visibility = v ? 'inherit' : 'hidden'; return v; };

// ---------- icons (24x24 stroke paths, one stroke width for the whole piece) ----------
const P = {
  play: 'M8 5.5v13l10.5-6.5z', pause: ['M8.5 5.5v13', 'M15.5 5.5v13'], check: 'M5 12.5l4.5 4.5L19 7.5',
  up: 'M12 19V5M5.5 11.5L12 5l6.5 6.5', down: 'M6 9.5l6 6 6-6', x: 'M6 6l12 12M18 6L6 18', plus: 'M12 5v14M5 12h14',
  search: ['M11 17.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z', 'M16 16l4.5 4.5'],
  star4: 'M12 3c.6 4.6 3.4 7.4 8 8-4.6.6-7.4 3.4-8 8-.6-4.6-3.4-7.4-8-8 4.6-.6 7.4-3.4 8-8z',
  heart: 'M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.3a4.3 4.3 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20z',
  comment: 'M20.5 11.6a8.5 8.5 0 1 1-4-7.2 8.5 8.5 0 0 1 4 7.2zM20.5 20.5l-2.3-4.3',
  send: 'M21 3.5L10.5 13.8M21 3.5l-6.6 17-3.9-6.7-6.9-3.8z',
  file: ['M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z', 'M14 3v5h5'],
  copy: ['M9 9h10v10H9z', 'M5 15V5h10'],
  person: ['M12 12.5a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4.5 21a7.5 7.5 0 0 1 15 0'],
  bell: ['M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z', 'M10 20.5h4'],
  volume: ['M4 9.5h3.5L12 5.5v13l-4.5-4H4z', 'M15.5 9a4.2 4.2 0 0 1 0 6', 'M18.3 6.5a8 8 0 0 1 0 11'],
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z',
  bolt: 'M13 2.5L4.5 13.5H12l-1 8L19.5 10.5H12z',
};
// icon centred at (x, y)
function icon(parent, paths, x, y, size, color, stroke = 2, fill = 'none') {
  const s = svgEl('svg', parent, { viewBox: '0 0 24 24', width: size, height: size });
  s.style.cssText = `position:absolute;left:${x - size / 2}px;top:${y - size / 2}px;overflow:visible`;
  for (const p of [].concat(paths)) svgEl('path', s, { d: p, fill, stroke: color, 'stroke-width': stroke, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
  return s;
}
// arrow cursor; the anchor group's origin is the tip. Scale it (tf s: 0.86) for a press.
function cursor(parent, size = 62, fill = C.INK, stroke = C.WHITE) {
  const g = grp(parent, 0, 0);
  const s = svgEl('svg', g, { viewBox: '-3 -3 67 89', width: size, height: size * 89 / 67 });
  s.style.cssText = 'position:absolute;left:-2px;top:-2px;overflow:visible';
  svgEl('path', s, { d: 'M 0 0 L 4 68 L 21 54 L 35 82 L 49 76 L 35 49 L 61 49 Z', fill, stroke, 'stroke-width': 4, 'stroke-linejoin': 'round' });
  return g;
}

// ---------- measurements the scene reports on purpose (printed by render.py) ----------
window.REPORT = {};
function report(key, value) { window.REPORT[key] = typeof value === 'number' ? +value.toFixed(3) : value; }

// ---------- sound cues (collected at build time, synthesised by audio.py) ----------
// kinds: click tick key pop popHi hit impact sub thud whoosh swish rise ding chime success glitch shutter count boing sparkle
window.SFX = [];
let SFX_ON = true;
function sfx(t, kind, g = 1) { if (SFX_ON && t >= 0 && t < DUR) window.SFX.push([+t.toFixed(4), kind, g]); }

// ---------- scenes ----------
const PRELOAD = [];   // promises a build can push (e.g. img.decode()); awaited before the first seek
const SCENES = [];
let LIVE = [];
// build(root, ctx) runs once and returns seek(t) (global t). root is a W x H box clipped to itself.
function scene(id, a, b, opts, build) { SCENES.push(Object.assign({ id, a, b, build, bg: 'transparent' }, opts)); }
function mount(sc, parent) {
  const root = div(parent, { background: sc.bg, width: W + 'px', height: H + 'px' }, 'scene');
  const ctx = Object.assign(Object.create(sc), { root });
  let seek = () => {};
  root.style.display = 'block';   // visible while building: getBBox and isPointInFill return 0 inside display:none
  try { seek = sc.build(root, ctx) || seek; } catch (e) { console.error(`scene ${sc.id} build failed: ${e.stack}`); }
  root.style.display = 'none';
  return { root, ctx, seek };
}
// a second live copy of a scene (e.g. recap tiles). No sound cues. Seek it with any t you like.
function instance(id, parent) {
  const sc = SCENES.find(s => s.id === id); if (!sc) return null;
  const was = SFX_ON; SFX_ON = false; const m = mount(sc, parent); SFX_ON = was;
  m.root.style.display = 'block'; return m;
}

// ---------- engine ----------
function seek(t) {
  t = CFG.loop ? ((t % DUR) + DUR) % DUR : clamp(t, 0, DUR);
  for (const sc of LIVE) {
    if (t >= sc.a && t < sc.b || (t === DUR && sc.b >= DUR)) {
      sc.root.style.display = 'block';
      try { sc.seek(t); } catch (e) { console.error(`scene ${sc.id} seek(${t}) failed: ${e.stack}`); }
    } else if (sc.root.style.display !== 'none') sc.root.style.display = 'none';
  }
}
window.seek = seek;
const FONT_LOADS = ['900 100px "Noto Sans Hebrew"', '400 100px "Noto Sans Hebrew"', '700 100px Rubik', '400 100px Rubik',
  '700 100px Heebo', '900 100px Archivo', '600 100px "JetBrains Mono"', '400 100px "Amatic SC"', '700 100px "Amatic SC"'];
window.ready = (async () => {
  await Promise.all(FONT_LOADS.flatMap(f => [document.fonts.load(f, 'אבגדה'), document.fonts.load(f, 'Abc 0123')]));
  await document.fonts.ready;
  const stage = $('stage');
  Object.assign(stage.style, { width: W + 'px', height: H + 'px', background: CFG.bg });
  SCENES.sort((p, q) => p.a - q.a);
  const host = $('scenes');
  LIVE = SCENES.map((sc, i) => { const m = mount(sc, host); m.root.style.zIndex = i + 1; return Object.assign(m, { id: sc.id, a: sc.a, b: sc.b }); });
  await Promise.all(PRELOAD);
  window.SFX.sort((p, q) => p[0] - q[0]);
  const q = new URLSearchParams(location.search);
  seek(q.has('t') ? +q.get('t') : 0);
  return true;
})();
