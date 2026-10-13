// ===================================================================
// Door leaf models. Built once per (kind, width, height) and instanced.
// A leaf runs from its hinge along +x for its width, from y = 0 up to its
// height, centred on z; both faces are modelled since it swings.
// ===================================================================
import { GeoBuilder, A, tint } from './builder';
import { M } from './mat';
import type { DoorKind } from '../world/doors';

export const doorKey = (kind: DoorKind, w: number, h: number) => `${kind}:${w.toFixed(2)}:${h.toFixed(2)}`;

export function buildDoor(b: GeoBuilder, key: string) {
  const [kind, ws, hs] = key.split(':');
  const w = +ws, h = +hs;
  const brass = A('#a8925a', M.CHROME);
  const knob = (x: number, y: number) => { for (const z of [-1, 1]) { b.box(x, y, z * 0.045, 0.11, 0.022, 0.022, brass); b.box(x + 0.04, y, z * 0.03, 0.03, 0.05, 0.03, brass); } };
  if (kind === 'inner') {
    // a cream painted panel door: frame, a frosted pane in the upper part, two panels below
    const t = 0.04, paint = A('#d6ceb6', M.PAINT, { seed: 0.4 });
    b.boxMM(0, 0, -t / 2, w, h, t / 2, paint);
    b.boxMM(0.14, h * 0.48, -t / 2 - 0.003, w - 0.14, h - 0.14, t / 2 + 0.003, A('#b8bcb4', M.LACE, { seed: 0.3 }));
    for (const z of [-1, 1]) for (const [y0, y1] of [[0.14, h * 0.24], [h * 0.27, h * 0.43]]) b.boxMM(0.12, y0, z * (t / 2) - 0.004, w - 0.12, y1, z * (t / 2) + 0.004, tint(paint, 0.92));
    knob(w - 0.09, 1.0);
  } else if (kind === 'front') {
    // the flat's front door: padded brown leatherette held by studs in diamonds, a spy-hole, the flat number
    const t = 0.055, pad = A('#4a2e1e', M.UPHOLSTERY, { seed: 0.5 });
    b.boxMM(0, 0, -t / 2, w, h, t / 2, pad);
    const stud = A('#b09a62', M.CHROME);
    for (let y = 0.25; y < h - 0.15; y += 0.24) for (let x = 0.12; x < w - 0.08; x += 0.2) {
      const off = Math.round(y / 0.24) % 2 ? 0.1 : 0;
      if (x + off < w - 0.08) b.box(x + off, y, -t / 2 - 0.006, 0.018, 0.018, 0.012, stud);
    }
    b.tube([w / 2, 1.55, -t / 2 - 0.01], [w / 2, 1.55, t / 2 + 0.01], 0.01, 0.01, 6, brass);
    b.boxMM(w / 2 - 0.05, 1.68, -t / 2 - 0.008, w / 2 + 0.05, 1.74, -t / 2 - 0.004, brass);
    knob(w - 0.09, 1.0);
    b.box(w - 0.09, 1.12, -t / 2 - 0.01, 0.03, 0.06, 0.01, A('#2a2622', M.METAL)); // the lock
  } else if (kind === 'lobby' || kind === 'works') {
    // block entrance: a varnished frame with wired glass above a solid kick panel (or plain steel for a workshop)
    const t = 0.05;
    const fr = kind === 'works' ? A('#4a5a52', M.METAL, { seed: 0.5 }) : A('#5a4632', M.WOOD, { seed: 0.4 });
    if (kind === 'works') { b.boxMM(0, 0, -t / 2, w, h, t / 2, fr); for (let y = 0.4; y < h; y += 0.6) b.boxMM(0, y, -t / 2 - 0.01, w, y + 0.05, t / 2 + 0.01, tint(fr, 0.8)); }
    else {
      const fw = 0.09;
      b.boxMM(0, 0, -t / 2, w, 0.9, t / 2, fr);                       // kick panel
      b.boxMM(0, h - fw, -t / 2, w, h, t / 2, fr);
      b.boxMM(0, 0.9, -t / 2, fw, h, t / 2, fr); b.boxMM(w - fw, 0.9, -t / 2, w, h, t / 2, fr);
      b.boxMM(fw, 0.9, -0.006, w - fw, h - fw, 0.006, A('#000000', M.GLASS, { seed: 0.2 }));
      b.boxMM(0.05, 1.0, -t / 2 - 0.012, w - 0.05, 1.04, t / 2 + 0.012, A('#8a8a84', M.CHROME)); // push bar
    }
    knob(w - 0.1, 1.05);
  } else if (kind === 'house') {
    // vertical planks with a Z brace on the inside and a small window
    const t = 0.045, wood = A('#5a4028', M.WOOD, { seed: 0.6 });
    b.boxMM(0, 0, -t / 2, w, h, t / 2, wood);
    b.boxMM(0.1, h * 0.65, -t / 2 - 0.004, w - 0.1, h * 0.88, t / 2 + 0.004, A('#000000', M.GLASS, { seed: 0.1 }));
    for (const y of [0.25, h * 0.55]) b.boxMM(0.05, y, t / 2, w - 0.05, y + 0.1, t / 2 + 0.025, tint(wood, 0.85));
    knob(w - 0.09, 1.0);
  } else if (kind === 'shop') {
    const t = 0.045, al = A('#9a9a92', M.CHROME);
    b.boxMM(0, 0, -t / 2, w, 0.12, t / 2, al); b.boxMM(0, h - 0.07, -t / 2, w, h, t / 2, al);
    b.boxMM(0, 0, -t / 2, 0.06, h, t / 2, al); b.boxMM(w - 0.06, 0, -t / 2, w, h, t / 2, al);
    b.boxMM(0.06, 0.12, -0.005, w - 0.06, h - 0.07, 0.005, A('#000000', M.GLASS, { seed: 1 }));
    b.boxMM(w - 0.16, 0.7, -t / 2 - 0.03, w - 0.12, 1.4, t / 2 + 0.03, al);
  } else if (kind === 'garage') {
    // up-and-over steel: ribbed, painted, rusting at the bottom
    const t = 0.04, steel = A(['#3e5a3e', '#5a4a3a', '#4a5260', '#6a3a30'][Math.floor(w * 7) % 4], M.METAL, { seed: 0.7 });
    b.boxMM(0, 0, -t / 2, w, h, t / 2, steel);
    for (let x = 0.15; x < w - 0.1; x += 0.3) b.boxMM(x, 0.05, -t / 2 - 0.012, x + 0.04, h - 0.05, -t / 2, tint(steel, 0.85));
    b.box(w / 2, 0.9, -t / 2 - 0.03, 0.18, 0.03, 0.03, A('#2a2a2a', M.METAL));
  }
}
