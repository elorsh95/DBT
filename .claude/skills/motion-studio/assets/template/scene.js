// scene.js: the animation. Replace this stub. API reference: the header of core.js.
// Rules: build the DOM once inside scene(); the function you return must be a pure function of t
// (no Math.random, no Date, no timers, no CSS transitions, nothing remembered between calls).
(() => {
  'use strict';
  scene('main', 0, DUR, { bg: C.INK }, (root, ctx) => {
    const cam = grp(root, W / 2, H / 2);                  // camera: everything inside moves with it, 0,0 = frame centre
    const o = { font: F.D, weight: 900 };
    const size = fit('שלום', o, 840 * W / 1080, 520);     // about 840 of the 920 safe px: room for push and shake
    const word = txt(cam, 'שלום', Object.assign({ size, y: -0.1 * H, color: C.WHITE }, o));
    const from = Math.min(1.25, (W - 40) / (measure('שלום', Object.assign({ size }, o)).w * 1.04));   // the slam stays in frame
    const T0 = 0.4;
    sfx(T0, 'hit', 0.8);
    return t => {
      const k = slam(t, T0, from);
      tf(word, { s: k.s, o: k.o });
      const [sx, sy, sr] = shake(t, [[T0, 14]]);
      tf(cam, { x: sx, y: sy, s: 1 + 0.04 * t / DUR, r: sr - 0.6 * t / DUR });   // slow push and roll: never a frozen frame
    };
  });
})();
