// Example for style 08 (neon organic), tested at 1080x1920, 6 s, bg '#070B1A' (set DUR and bg in index.html CONFIG).
// A neuron whose central node sits in the upper half, a two-line title under it, roots that part around the title plate
// and meet again below it, and the whole tree inside the frame (with room for the camera pull back).
// To use it: copy it over scene.js, then change TITLE, the colours in LAYERS, and the T_ times. Render with SUB=8.
// The scene reports its measurements with report(): render.py check / stills print them (growthEnd, corridor, treeBounds).
(() => {
  'use strict';
  const TITLE = 'רעיון שנדלק בחושך';
  const BG = '#070B1A';
  const T_GROW0 = 0.15, T_GROW1 = 2.6, T_PULSE0 = 2.55, T_PULSE1 = 3.05, T_TITLE = 3.15, T_BOLT = 3.85;

  scene('main', 0, DUR, { bg: BG }, (root) => {
    const R = rng(11);
    const N = [W / 2, 0.30 * H];                       // central node, upper half

    // ---------- title: two lines, measured, and the plate around it ----------
    const words = TITLE.split(' ');
    const cut = Math.ceil(words.length / 2);
    const lines = [words.slice(0, cut), words.slice(cut)].filter(l => l.length);
    const fo = { font: F.D, weight: 900 };
    const size = Math.min(150, ...lines.map(l => fit(l.join(' '), fo, 0.5 * W)));   // narrow lines leave corridors for the roots
    const lineH = size * 1.12, titleY = N[1] + 330;
    const lineW = Math.max(...lines.map(l => measure(l.join(' '), Object.assign({ size }, fo)).w));
    const PL = { cx: W / 2, cy: titleY + (lines.length - 1) * lineH / 2, rx: lineW / 2 + 80, ry: lines.length * lineH / 2 + 70 };
    const M = [W / 2, PL.cy + PL.ry + 190];            // where the roots meet again
    const MX = 90, MY = 130;                           // soft walls: margin + camera push

    // ---------- growth: one walker, steered by waypoints, a pull back to its first direction, gravity,
    // the plate (soft repulsion) and the frame (soft push inward). All at build time, with a fixed seed. ----------
    const norm = v => { const l = Math.hypot(v[0], v[1]) || 1; return [v[0] / l, v[1] / l]; };
    const rot = (v, a) => [v[0] * Math.cos(a) - v[1] * Math.sin(a), v[0] * Math.sin(a) + v[1] * Math.cos(a)];
    function walk(p0, dir0, len, o) {
      const d0 = norm(dir0); let d = d0, p = p0.slice(), ti = 0; const pts = [p.slice()], step = 9, seed = R() * 100;
      for (let s = step; s <= len; s += step) {
        let f = d.slice();
        if (o.targets && ti < o.targets.length) {
          const tg = o.targets[ti], dx = tg[0] - p[0], dy = tg[1] - p[1], dl = Math.hypot(dx, dy) || 1;
          if (dl < 60 && ti < o.targets.length - 1) ti++;
          else if (dl < 45 && ti === o.targets.length - 1 && o.stop) { pts.push(tg.slice()); break; }   // arrived: end exactly on the target
          f[0] += o.wa * dx / dl; f[1] += o.wa * dy / dl;
        }
        f[0] += o.pull * d0[0]; f[1] += o.pull * d0[1] + o.grav;
        const ex = (p[0] - PL.cx) / PL.rx, ey = (p[1] - PL.cy) / PL.ry, q = Math.hypot(ex, ey);
        if (q < 1.25) { const k = (1.25 - q) * 4, n = norm([ex / PL.rx, ey / PL.ry]); f[0] += k * n[0]; f[1] += k * n[1]; }
        // the soft wall: 60 px of margin plus room for the camera push (6% of the distance from the centre)
        if (p[0] < MX) f[0] += 2 * (MX - p[0]) / MX; if (p[0] > W - MX) f[0] -= 2 * (p[0] - W + MX) / MX;
        if (p[1] < MY) f[1] += 2 * (MY - p[1]) / MY; if (p[1] > H - MY) f[1] -= 2 * (p[1] - H + MY) / MY;
        const nd = rot(norm(f), 0.35 * vnoise(s * 0.015, seed));
        d = norm([d[0] * 0.7 + nd[0] * 0.3, d[1] * 0.7 + nd[1] * 0.3]);
        p = [p[0] + d[0] * step, p[1] + d[1] * step];
        if (p[0] < MX - 30 || p[0] > W - MX + 30 || p[1] < MY - 40 || p[1] > H - MY + 40 || q < 1.0) break;
        pts.push(p.slice());
      }
      return pts;
    }
    const B = [];   // {pts, cum, len, depth, t0 (in path px from the node)}
    function add(pts, depth, t0) {
      const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
      const b = { pts, cum, len: cum[cum.length - 1], depth, t0 }; B.push(b); return b;
    }
    // children fan out from a parent at 20..35 degrees, shorter, pulled back to their own first direction
    function kids(par, maxDepth, o) {
      if (par.depth >= maxDepth) return;
      for (let i = 6; i < par.pts.length - 4; i += 7 + Math.floor(R() * 6)) {
        if (R() > o.prob) continue;
        const a = par.pts[i], b = par.pts[i + 1], dir = norm([b[0] - a[0], b[1] - a[1]]);
        const ang = (20 + R() * 15) * Math.PI / 180 * (R() < 0.5 ? -1 : 1);
        const len = (par.len - par.cum[i]) * (0.45 + R() * 0.2);
        if (len < 50) continue;
        const c = add(walk(a, rot(dir, ang), len, { wa: 0, pull: 0.25, grav: o.grav }), par.depth + 1, par.t0 + par.cum[i]);
        kids(c, maxDepth, o);
      }
    }
    // dendrites: up, each to its own point in the top band
    const up = 6;
    for (let k = 0; k < up; k++) {
      const tx = lerp(0.14 * W, 0.86 * W, k / (up - 1)), ty = lerp(0.07 * H, 0.14 * H, R());
      const d = add(walk(N, [tx - N[0], ty - N[1]], 620, { targets: [[tx, ty]], wa: 0.25, pull: 0.1, grav: -0.04 }), 0, 0);
      kids(d, 2, { prob: 0.55, grav: -0.05 });
    }
    // two roots: down around the plate through a side waypoint, then to M where they meet
    const roots = [-1, 1].map(side => {   // a guide path: out of the node, down the corridor beside the plate, in to M
      const gap = W / 2 - PL.rx - MX, X = k => PL.cx + side * (PL.rx + k * gap);   // k = 0.5: the middle of the corridor
      const guide = [[N[0] + side * 150, N[1] + 130], [X(0.45), PL.cy - 0.6 * PL.ry], [X(0.5), PL.cy], [X(0.4), PL.cy + 0.75 * PL.ry], M];
      const r = add(walk(N, [side * 0.7, 1], 1600, { targets: guide, wa: 0.55, pull: 0, grav: 0.05, stop: true }), 0, 0);
      kids(r, 1, { prob: 0.25, grav: 0.1 });
      return r;
    });
    // below the meeting point: a short trunk and roots that spread down, all inside the frame
    const lowT = Math.max(...roots.map(r => r.len));   // the lower tree starts when the roots meet
    const trunk = add(walk(M, [0, 1], 260, { targets: [[W / 2, M[1] + 260]], wa: 0.3, pull: 0.3, grav: 0.1 }), 0, lowT);
    for (let k = 0; k < 5; k++) {
      const tx = lerp(0.16 * W, 0.84 * W, k / 4), ty = H - 150 - R() * 60;
      const r = add(walk(trunk.pts[Math.min(trunk.pts.length - 1, 6 + k * 3)], [tx - W / 2, 1.2 * (ty - M[1])], 700,
        { targets: [[tx, ty]], wa: 0.3, pull: 0.1, grav: 0.12 }), 1, lowT + 60 + k * 25);
      kids(r, 2, { prob: 0.45, grav: 0.15 });
    }
    // one global growth clock, eased: every tip keeps its place in the order, and the whole growth eases in and out
    const tauMax = Math.max(...B.map(b => b.t0 + b.len));
    const tau = t => tauMax * E.o3(seg(t, T_GROW0, T_GROW1));   // fast start, gentle end: no dead opening
    const all = B.flatMap(b => b.pts);
    report('branches', B.length);
    report('growthEnd', T_GROW1);
    report('rootEnds', roots.map(r => r.pts[r.pts.length - 1].map(Math.round)));
    report('plate', [PL.cx - PL.rx, PL.cx + PL.rx].map(Math.round));
    report('corridor', W / 2 - PL.rx - MX);
    report('treeBounds', [Math.min(...all.map(p => p[0])), Math.min(...all.map(p => p[1])), Math.max(...all.map(p => p[0])), Math.max(...all.map(p => p[1]))].map(Math.round));

    // ---------- glow: about 10 layers, one continuous path per depth class and layer ----------
    const LAYERS = [[64, .018, '139,92,246'], [44, .026, '139,92,246'], [30, .036, '139,92,246'], [21, .05, '120,105,248'],
      [14, .07, '59,130,246'], [9, .1, '59,130,246'], [6, .15, '90,150,250'], [3.6, .26, '170,200,255'], [2.2, .5, '205,222,255'], [1.3, .9, '240,244,255']];
    const DEPTH_W = [1, 0.62, 0.42];
    const cam = div(root, { left: '0px', top: '0px', width: W + 'px', height: H + 'px', transformOrigin: `${W / 2}px ${0.47 * H}px` });   // the camera
    const g = canvas2d(cam);
    function tracePart(b, upto) {   // the drawn part of one branch as a sub path
      if (upto <= 0) return;
      g.moveTo(b.pts[0][0], b.pts[0][1]);
      for (let i = 1; i < b.pts.length; i++) {
        if (b.cum[i] <= upto) { g.lineTo(b.pts[i][0], b.pts[i][1]); continue; }
        const k = (upto - b.cum[i - 1]) / (b.cum[i] - b.cum[i - 1]);
        g.lineTo(lerp(b.pts[i - 1][0], b.pts[i][0], k), lerp(b.pts[i - 1][1], b.pts[i][1], k)); break;
      }
    }
    // pulse: along the longest dendrite, from its tip into the node
    const pb = B.filter(b => b.depth === 0 && b.pts[b.pts.length - 1][1] < N[1]).sort((a, b) => b.len - a.len)[0];
    const at = (b, s) => { let i = 1; while (i < b.cum.length - 1 && b.cum[i] < s) i++; const k = clamp((s - b.cum[i - 1]) / (b.cum[i] - b.cum[i - 1] || 1), 0, 1); return [lerp(b.pts[i - 1][0], b.pts[i][0], k), lerp(b.pts[i - 1][1], b.pts[i][1], k)]; };
    // the far jagged bolt, built once
    const bolt = [[0.9 * W, 0.01 * H]];
    for (let i = 0; i < 26; i++) { const p = bolt[bolt.length - 1]; bolt.push([p[0] + (R() - 0.5) * 60, p[1] + 16 + R() * 24]); }
    // dust
    const dust = Array.from({ length: 220 }, (_, i) => [hash(i) * W, hash(i + 99) * H, 12 + 30 * hash(i + 7), 0.6 + 1.4 * hash(i + 3)]);
    function halo(x, y, r, rgb, a) {
      const gr = g.createRadialGradient(x, y, 0, x, y, r);
      for (let k = 0; k <= 16; k++) { const u = k / 16; gr.addColorStop(u, `rgba(${rgb},${(a * (1 - u) ** 2.2).toFixed(4)})`); }
      g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
    }

    // ---------- title plate: many stops (no rings) + a fine static grain above everything ----------
    const plate = div(cam, { left: '0px', top: '0px', width: W + 'px', height: H + 'px' });
    const stops = Array.from({ length: 25 }, (_, k) => { const u = k / 24, a = 0.9 * (1 - E.smooth(u)); return `rgba(7,11,26,${a.toFixed(3)}) ${(u * 100).toFixed(1)}%`; });
    plate.style.background = `radial-gradient(ellipse ${Math.round(PL.rx * 1.35)}px ${Math.round(PL.ry * 1.45)}px at ${PL.cx}px ${PL.cy}px, ${stops.join(',')})`;
    const tl = lines.map((l, i) => row(cam, l, Object.assign({ x: W / 2, y: titleY + i * lineH, size, color: '#F4F1EC' }, fo)));
    const grain = canvas2d(root); { const id = grain.createImageData(W, H), r2 = rng(5); for (let i = 0; i < id.data.length; i += 4) { const v = 255 * r2(); id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 10; } grain.putImageData(id, 0, 0); }

    sfx(T_GROW0, 'rise', 0.7); sfx(T_PULSE0, 'glitch', 0.4); sfx(T_PULSE1, 'impact', 0.9); sfx(T_BOLT, 'sub', 0.8);
    tl.flat().forEach((w, i) => sfx(T_TITLE + 0.12 * i, 'hit', 0.5));

    return t => {
      g.clearRect(0, 0, W, H);
      tf(cam, { s: 1.06 - 0.06 * E.o2(t / DUR) });   // a slow pull back: the picture never stands still
      const breathe = t > T_TITLE ? 0.85 + 0.15 * Math.sin(2 * Math.PI * 0.5 * (t - T_TITLE)) : 1;
      // dust
      g.fillStyle = 'rgba(150,170,255,0.35)';
      dust.forEach(([x, y, v, r]) => { g.beginPath(); g.arc(x, (y + t * v) % H, r, 0, 7); g.fill(); });
      // far bolt: 0.15 s, and the background lifts once
      const bu = t - T_BOLT;
      if (bu >= 0 && bu < 0.6) {
        g.fillStyle = `rgba(110,90,240,${(0.1 * Math.exp(-bu * 9)).toFixed(4)})`; g.fillRect(0, 0, W, H);
        if (bu < 0.15) { g.globalCompositeOperation = 'lighter'; g.strokeStyle = `rgba(190,180,255,${(0.5 * (1 - bu / 0.15)).toFixed(3)})`; g.lineWidth = 3;
          g.beginPath(); bolt.forEach((p, i) => i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.stroke(); g.globalCompositeOperation = 'source-over'; }
      }
      // tree
      const tt = tau(t);
      g.globalCompositeOperation = 'lighter'; g.lineCap = 'round'; g.lineJoin = 'round';
      LAYERS.forEach(([w, a, rgb]) => DEPTH_W.forEach((dw, depth) => {
        g.beginPath(); B.forEach(b => { if (b.depth === depth) tracePart(b, tt - b.t0); });
        g.lineWidth = w * dw; g.strokeStyle = `rgba(${rgb},${(a * breathe).toFixed(4)})`; g.stroke();
      }));
      // light point at the node
      const lp = clamp((t - 0.1) / 0.25, 0, 1);
      halo(N[0], N[1], 70, '200,210,255', 0.8 * lp);
      // pulse into the node, then the flare
      if (t >= T_PULSE0 && t < T_PULSE1 + 0.05) {
        const s = pb.len * (1 - E.io3(seg(t, T_PULSE0, T_PULSE1)));
        for (let k = 0; k < 8; k++) { const q = at(pb, s + k * 9); halo(q[0], q[1], 26 - k * 2, '253,224,71', 0.9 * (1 - k / 8)); }
      }
      const fl = t >= T_PULSE1 ? S(t - T_PULSE1, 20, 0.6) : 0;
      if (fl > 0) halo(N[0], N[1], 60 + 240 * fl, '253,224,71', 0.55 * Math.exp(-(t - T_PULSE1) * 2.2) + 0.12 * breathe);
      g.globalCompositeOperation = 'source-over';
      // plate and title
      const po = clamp((t - T_TITLE + 0.2) / 0.3, 0, 1);
      tf(plate, { o: po });
      tl.flat().forEach((w, i) => { const k = rise(t, T_TITLE + 0.12 * i, 40); tf(w.g, { o: k.o, y: k.y }); });
    };
  });
})();
