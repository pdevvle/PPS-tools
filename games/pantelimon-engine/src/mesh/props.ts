// ===================================================================
// Street furniture models, each built once and instanced: bare winter
// trees, the concrete lamp posts with rectangular holes, Dacias and
// Trabants, benches and refuse containers. Model keys are
// `${type}:${variant}`.
// ===================================================================
import { GeoBuilder, A, withA, type V3 } from './builder';
import { M } from './mat';

const TAU = Math.PI * 2;
const clamp = (x: number, a: number, b: number) => (x < a ? a : x > b ? b : x);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
function mulberry32(a: number) {
  return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scl = (a: V3, k: number): V3 => [a[0] * k, a[1] * k, a[2] * k];
const norm = (a: V3): V3 => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const lerp3 = (a: V3, b: V3, t: number): V3 => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

// ---------------------------------------------------------------- bare deciduous trees
const TREES = ['linden', 'plane', 'poplar', 'acacia'] as const;
function tree(b: GeoBuilder, variant: number) {
  const kind = TREES[variant % 4];
  const rnd = mulberry32(1000 + variant * 77);
  const plane = kind === 'plane' ? 1 : 0;
  const barkCol = kind === 'plane' ? '#7a7466' : kind === 'poplar' ? '#4a4840' : '#3a332c';
  const sway = (y: number) => clamp((y - 2.5) / 12, 0, 1);
  const shape = {
    linden: { trunk: 3.0, len: 3.2, spread: 0.75, up: 0.55, depth: 5, kids: [3, 2], r: 0.24 },
    plane: { trunk: 3.6, len: 3.8, spread: 0.85, up: 0.35, depth: 5, kids: [3, 2], r: 0.3 },
    poplar: { trunk: 2.6, len: 4.2, spread: 0.32, up: 1.4, depth: 5, kids: [3, 2], r: 0.26 },
    acacia: { trunk: 2.2, len: 2.6, spread: 0.95, up: 0.3, depth: 5, kids: [2, 3], r: 0.2 },
  }[kind];
  let segs = 0;
  const mistletoe: V3[] = [];
  const grow = (p: V3, dir: V3, len: number, r: number, depth: number) => {
    if (segs > 360) return;
    const bend: V3 = [(rnd() - 0.5) * 0.4, (rnd() - 0.2) * 0.2, (rnd() - 0.5) * 0.4];
    const mid = add(add(p, scl(dir, len * 0.5)), scl(bend, len * 0.15));
    const end = add(add(p, scl(dir, len)), scl(bend, len * 0.1));
    const sides = depth < 2 ? 7 : depth < 3 ? 5 : 3;
    b.tube(p, mid, r, r * 0.86, sides, A(barkCol, M.BARK, { seed: rnd(), snow: 0.6, aux: [sway(p[1]), plane] }), false);
    b.tube(mid, end, r * 0.86, r * 0.7, sides, A(barkCol, M.BARK, { seed: rnd(), snow: 0.6, aux: [sway(mid[1]), plane] }), depth > 3);
    segs += 2;
    if (depth >= shape.depth || r < 0.01) return;
    const nk = shape.kids[depth === 0 ? 0 : 1] + (rnd() < 0.35 ? 1 : 0);
    const nd = norm([end[0] - p[0], end[1] - p[1], end[2] - p[2]]);
    for (let i = 0; i < nk; i++) {
      const ang = (i / nk) * TAU + rnd() * 1.2;
      let d: V3 = add(add(scl(nd, 0.6), scl([Math.cos(ang), 0, Math.sin(ang)], shape.spread * (0.6 + rnd() * 0.6))), [0, shape.up * (0.5 + rnd() * 0.5), 0]);
      d = norm(d);
      if (depth > 2) d = norm([d[0], d[1] - 0.15 * (depth - 2), d[2]]);
      grow(i === 0 ? end : lerp3(p, end, 0.55 + rnd() * 0.4), d, len * (0.62 + rnd() * 0.15), r * (0.6 + rnd() * 0.08), depth + 1);
    }
    if (depth >= shape.depth - 1) {
      for (let i = 0; i < 3; i++) {
        const d = norm(add(nd, [rnd() - 0.5, rnd() * 0.6, rnd() - 0.5]));
        b.tube(end, add(end, scl(d, len * 0.45)), r * 0.5, 0.004, 3, A(barkCol, M.BARK, { seed: rnd(), aux: [sway(end[1]) + 0.2, plane] }), false);
        segs++;
      }
    }
    if ((kind === 'poplar' || kind === 'acacia') && depth === 3 && rnd() < 0.12) mistletoe.push(end);
  };
  const top: V3 = [(rnd() - 0.5) * 0.2, shape.trunk, (rnd() - 0.5) * 0.2];
  b.tube([0, -0.2, 0], [0, 1.2, 0], shape.r * 1.08, shape.r, 9, A(barkCol, M.BARK, { seed: rnd(), aux: [0, plane] }), false);
  b.tube([0, 1.2, 0], top, shape.r, shape.r * 0.85, 9, A(barkCol, M.BARK, { seed: rnd(), aux: [0, plane] }), false);
  grow(top, [0, 1, 0], shape.len, shape.r * 0.85, 0);
  // mistletoe (vâsc) clumps, a common winter sight
  const mst = A('#2e3a1e', M.PLAIN, { seed: rnd(), aux: [0.6, 0] });
  for (const p of mistletoe.slice(0, 2)) b.push().translate(p[0], p[1], p[2]).blob(0.18 + rnd() * 0.1, mst, rnd, 1, 0.8, 1, 0.45).pop();
}

// ---------------------------------------------------------------- concrete lamp post with rectangular holes; the arm reaches toward +z
function lamppost(b: GeoBuilder, variant: number) {
  const height = 8.5;
  const conc = A('#8e8b84', M.CONCRETE, { seed: 0.3 + variant * 0.1 });
  const w0 = 0.34, w1 = 0.17, d = 0.2, fl = 0.055, steps = 10;
  for (let i = 0; i < steps; i++) {
    const y0 = (i / steps) * height, y1 = ((i + 1) / steps) * height;
    const w = lerp(w0, w1, (i + 0.5) / steps);
    b.box(0, (y0 + y1) / 2, -w / 2 + fl / 2, d, y1 - y0 + 0.001, fl, conc);
    b.box(0, (y0 + y1) / 2, w / 2 - fl / 2, d, y1 - y0 + 0.001, fl, conc);
    const solid = i < 1 ? 1 : 0.35;
    b.box(0, y0 + ((y1 - y0) * solid) / 2, 0, 0.06, (y1 - y0) * solid, w - fl * 2 + 0.002, conc);
  }
  b.box(0, height + 0.03, 0, d + 0.02, 0.06, w1 + 0.02, conc);
  if (variant === 1) return; // the lamp was never fitted, or was taken
  const arm = A('#4e524f', M.METAL, { seed: 0.5 });
  const reach = 1.6;
  const pts: V3[] = [];
  for (let i = 0; i <= 6; i++) { const t = i / 6; pts.push([0, height - 1.2 + Math.sin(t * Math.PI * 0.5) * 1.3, 0.1 + t * reach]); }
  for (let i = 0; i < 6; i++) b.tube(pts[i], pts[i + 1], 0.04, 0.035, 5, arm, false);
  const e = pts[6];
  b.push().translate(0, e[1] - 0.05, e[2] + 0.2);
  b.lathe([[0.0, 0.05], [0.34, 0.0], [0.3, -0.12], [0.0, -0.14]], 10, arm);
  b.lathe([[0.27, -0.12], [0.0, -0.16]], 10, A([1, 0.75, 0.45], M.LAMP, { aux: [5, 0] }));
  b.pop();
}
/** Where the lamp head sits, model space (for the point lights). */
export const LAMP_HEAD: V3 = [0, 8.5 - 0.45, 1.9];

// ---------------------------------------------------------------- cars of 1989
const CAR_TYPES = {
  dacia: { L: 4.35, W: 1.64, wb: 2.44, wr: 0.3, belt: 0.98, roof: 1.42, nose: 0.88, tail: 0.96, ws0: 0.86, ws1: 0.22, rw0: -0.86, rw1: -1.36, estate: false },
  break: { L: 4.42, W: 1.64, wb: 2.44, wr: 0.3, belt: 0.98, roof: 1.46, nose: 0.88, tail: 0.98, ws0: 0.86, ws1: 0.22, rw0: -2.12, rw1: -2.18, estate: true },
  trabant: { L: 3.56, W: 1.5, wb: 2.02, wr: 0.28, belt: 0.92, roof: 1.42, nose: 0.82, tail: 0.92, ws0: 0.6, ws1: 0.05, rw0: -0.85, rw1: -1.3, estate: false },
};
const CAR_COLOURS = ['#8a8a7e', '#6a2a22', '#3a4a5a', '#c8c0a8', '#4a5a3e', '#9a7a3a', '#2a3a4a', '#a8a090', '#5a3a2a'];
function car(b: GeoBuilder, variant: number) {
  const type = variant % 9 === 4 ? 'trabant' : variant % 9 === 7 ? 'break' : 'dacia';
  const T = CAR_TYPES[type];
  const L = T.L, W = T.W, hl = L / 2;
  const tarp = variant >= 9 && variant % 3 === 0;
  const blocks = variant >= 9 && !tarp;
  const paintA = A(tarp ? '#4a5244' : CAR_COLOURS[variant % 9], tarp ? M.CLOTH : M.PAINT, { seed: (variant * 0.37) % 1, snow: 1 });
  const glassA = tarp ? paintA : A('#000000', M.GLASS);
  const chrome = A('#888888', M.CHROME), rubber = A('#111111', M.RUBBER);
  b.push().translate(0, blocks ? 0.12 : 0, 0);
  const prof: [number, number][] = [[-hl, 0.3], [hl - 0.05, 0.3], [hl + 0.02, 0.5], [hl, T.nose - 0.06], [hl - 0.25, T.nose], [T.ws0, T.belt], [T.rw1, T.belt], [-hl + 0.18, T.tail], [-hl - 0.02, T.tail - 0.1], [-hl - 0.02, 0.5]];
  const zs = [W / 2, -W / 2];
  const ring = (z: number) => prof.map(([x, y]) => [x, y, z] as V3);
  const oL = ring(zs[0]), oR = ring(zs[1]);
  for (let s = 0; s < 2; s++) {
    const pts = s === 0 ? oL : oR, c: V3 = [0, 0.62, zs[s]], n: V3 = [0, 0, s === 0 ? 1 : -1];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], q = pts[(i + 1) % pts.length];
      if (s === 0) b.tri(c, a, q, n, n, n, [c[0], c[1]], [a[0], a[1]], [q[0], q[1]], paintA);
      else b.tri(c, q, a, n, n, n, [c[0], c[1]], [q[0], q[1]], [a[0], a[1]], paintA);
    }
  }
  for (let i = 0; i < prof.length; i++) { const j = (i + 1) % prof.length; b.quad(oL[i], oR[i], oR[j], oL[j], paintA); }
  const gw0 = W / 2 - 0.07, gw1 = W / 2 - 0.2, rearTop = T.estate ? -hl + 0.1 : T.rw0;
  const bfL: V3 = [T.ws0, T.belt, gw0], bfR: V3 = [T.ws0, T.belt, -gw0], brL: V3 = [T.rw1, T.belt, gw0], brR: V3 = [T.rw1, T.belt, -gw0];
  const tfL: V3 = [T.ws1, T.roof, gw1], tfR: V3 = [T.ws1, T.roof, -gw1], trL: V3 = [rearTop, T.roof, gw1], trR: V3 = [rearTop, T.roof, -gw1];
  b.quad(bfL, bfR, tfR, tfL, glassA); b.quad(brR, brL, trL, trR, glassA); b.quad(tfL, tfR, trR, trL, paintA);
  b.quad(brL, bfL, tfL, trL, tarp ? paintA : glassA); b.quad(bfR, brR, trR, tfR, tarp ? paintA : glassA);
  if (!tarp) for (const s of [1, -1]) { // B pillar
    const z = s * (gw0 - 0.005), zt = s * (gw1 - 0.005), x = (T.ws0 + T.rw1) / 2 - 0.1, xt = (T.ws1 + rearTop) / 2;
    b.quad([x - 0.04, T.belt, z], [x + 0.04, T.belt, z], [xt + 0.04, T.roof, zt], [xt - 0.04, T.roof, zt], s > 0 ? paintA : withA(paintA, {}));
  }
  for (const x of [T.wb / 2 - 0.05, -T.wb / 2 - 0.05]) for (const s of [1, -1]) {
    const z = s * (W / 2 - 0.12);
    if (blocks) { b.box(x, -0.02, z, 0.4, 0.2, 0.2, A('#77736b', M.CONCRETE)); b.box(x, 0.18, z, 0.4, 0.2, 0.2, A('#6f6b63', M.CONCRETE)); }
    else { b.tube([x, T.wr, z - 0.09], [x, T.wr, z + 0.09], T.wr, T.wr, 12, rubber, true); b.tube([x, T.wr, z + s * 0.09], [x, T.wr, z + s * 0.1], T.wr * 0.62, T.wr * 0.55, 10, chrome, true); }
  }
  if (!tarp) {
    b.box(hl + 0.04, 0.42, 0, 0.08, 0.1, W + 0.04, chrome);
    b.box(-hl - 0.05, 0.44, 0, 0.08, 0.1, W + 0.04, chrome);
    b.box(hl + 0.015, 0.66, 0, 0.03, 0.2, W * 0.62, A('#141414', M.RUBBER));
    const lampA = A([1, 0.92, 0.75], M.LAMP, { aux: [0, 0] });
    for (const s of [1, -1]) b.facade(hl + 0.032, 0.6, s > 0 ? W / 2 - 0.06 : -W / 2 + 0.34, [1, 0, 0], 0.28, 0.16, lampA);
    for (const s of [1, -1]) b.facade(-hl - 0.032, 0.62, s > 0 ? W / 2 - 0.3 : -W / 2 + 0.08, [-1, 0, 0], 0.22, 0.2, A([0.8, 0.08, 0.05], M.LAMP, { aux: [0, 0] }));
    b.box(hl + 0.06, 0.36, 0, 0.01, 0.11, 0.52, A('#d8d8d0', M.PAINT));
  }
  b.pop();
}

function bench(b: GeoBuilder) {
  const conc = A('#8a867e', M.CONCRETE), wood = A('#5e4630', M.WOOD, { seed: 0.4, snow: 1 });
  for (const s of [-0.75, 0.75]) b.box(s, 0.22, 0, 0.12, 0.44, 0.45, conc);
  for (let i = 0; i < 3; i++) b.box(0, 0.46, -0.15 + i * 0.15, 1.8, 0.04, 0.11, wood);
  for (let i = 0; i < 2; i++) b.box(0, 0.65 + i * 0.16, -0.24, 1.8, 0.11, 0.04, wood);
}
function bin(b: GeoBuilder) {
  b.box(0, 0.65, 0, 1.6, 1.1, 1.1, A('#4a5a4a', M.METAL, { seed: 0.9 }));
  b.box(0, 1.24, 0, 1.65, 0.06, 1.15, A('#3e4a3e', M.METAL, { snow: 1 }));
  b.box(0, 0.06, 0, 1.5, 0.12, 1.0, A('#1a1a1a', M.RUBBER));
}

export function buildProp(b: GeoBuilder, key: string) {
  const [type, v] = key.split(':');
  const variant = +v || 0;
  if (type === 'tree') tree(b, variant);
  else if (type === 'lamppost') lamppost(b, variant);
  else if (type === 'car') car(b, variant);
  else if (type === 'bench') bench(b);
  else if (type === 'bin') bin(b);
}
/** Collision footprint radius of each prop type (cars are boxes, handled separately). */
export const PROP_RADIUS: Record<string, number> = { tree: 0.35, lamppost: 0.22, bench: 0.5, bin: 0.75 };
