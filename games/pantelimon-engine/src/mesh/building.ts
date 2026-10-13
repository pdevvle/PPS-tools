// ===================================================================
// Building meshes from a BuildingPlan.
//   far  — the exterior only: facades with interior-mapped windows,
//          balconies, roofs, entrance steps. Merged per streaming tile.
//   near — the same exterior with real openings and glass, plus every
//          room: floors, ceilings, papered walls with door and window
//          reveals, stairs, landings, railings and all the furniture.
// Output is in building-local coordinates unless the caller has set a
// transform on the builder.
// ===================================================================
import type { BuildingPlan, FurnitureItem, Opening, Room } from '../data/schema';
import { GeoBuilder, A, withA, tint, type Attr, type V3 } from './builder';
import { M, lin } from './mat';
import { rngFor } from '../core/rng';
import { exteriorSteps, EXT, INT } from '../world/extras';

type Side = 'n' | 's' | 'e' | 'w';
interface Hole { t0: number; t1: number; y0: number; y1: number; kind: Opening['kind']; room: Room; o: Opening }
interface Plane { side: Side; c: number; t0: number; t1: number; holes: Hole[] }

const HOUSE = ['#c9b48c', '#b8c2ae', '#d2c4a8', '#c4a88e', '#d6ccb4', '#bfb39a', '#c8bca0', '#a9b7b9', '#d0b0a0'];
const WALLPAPER = ['#8a7a5a', '#6e7a6a', '#8a6a5a', '#7a7a8a', '#9a8a6a', '#6a6a52', '#8a7a7a', '#7a6a4a'];
const DADO = ['#3e5a4a', '#3a4a5e', '#6a5a3a', '#4a5a5a'];
const outward = (s: Side): V3 => (s === 'n' ? [0, 0, -1] : s === 's' ? [0, 0, 1] : s === 'w' ? [-1, 0, 0] : [1, 0, 0]);
/** Point on a wall plane: t along it, y up, d outward from the plane. */
function onPlane(side: Side, c: number, t: number, y: number, d: number): V3 {
  return side === 'n' ? [t, y, c - d] : side === 's' ? [t, y, c + d] : side === 'w' ? [c - d, y, t] : [c + d, y, t];
}
/** Quad whose winding is fixed up to face `want`. */
function quadFacing(b: GeoBuilder, p: V3[], a: Attr, want: V3, uvs?: [number, number][]) {
  const e1 = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]], e2 = [p[3][0] - p[0][0], p[3][1] - p[0][1], p[3][2] - p[0][2]];
  const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
  if (n[0] * want[0] + n[1] * want[1] + n[2] * want[2] < 0) b.quad(p[3], p[2], p[1], p[0], a, uvs ? [uvs[3], uvs[2], uvs[1], uvs[0]] : undefined);
  else b.quad(p[0], p[1], p[2], p[3], a, uvs);
}
/** A wall rectangle on a plane, facing `face` (+1 outward, −1 inward), uv in metres along t and y. */
function wallRect(b: GeoBuilder, side: Side, c: number, t0: number, t1: number, y0: number, y1: number, a: Attr, face: 1 | -1, vOff = 0) {
  if (t1 - t0 < 1e-3 || y1 - y0 < 1e-3) return;
  const n = outward(side);
  const want: V3 = [n[0] * face, 0, n[2] * face];
  // uv u increases along cross(up, normal) so panel joints and the window shader line up
  const sgn = side === 's' || side === 'w' ? 1 : -1;
  const us = (t: number) => t * sgn * face;
  const p: V3[] = [onPlane(side, c, t0, y0, 0), onPlane(side, c, t1, y0, 0), onPlane(side, c, t1, y1, 0), onPlane(side, c, t0, y1, 0)];
  quadFacing(b, p, a, want, [[us(t0), y0 - vOff], [us(t1), y0 - vOff], [us(t1), y1 - vOff], [us(t0), y1 - vOff]]);
}
/** A wall with rectangular holes, built band by band. */
function wallWithHoles(b: GeoBuilder, side: Side, c: number, t0: number, t1: number, y0: number, y1: number, holes: { t0: number; t1: number; y0: number; y1: number }[], a: Attr, face: 1 | -1, vOff = 0, split?: { y: number; a: Attr }) {
  const ys = new Set<number>([y0, y1]);
  if (split && split.y > y0 && split.y < y1) ys.add(split.y);
  const hs = holes.filter((h) => h.t1 > t0 && h.t0 < t1 && h.y1 > y0 && h.y0 < y1).map((h) => ({ t0: Math.max(h.t0, t0), t1: Math.min(h.t1, t1), y0: Math.max(h.y0, y0), y1: Math.min(h.y1, y1) }));
  for (const h of hs) { ys.add(h.y0); ys.add(h.y1); }
  const Y = [...ys].sort((p, q) => p - q);
  for (let i = 0; i < Y.length - 1; i++) {
    const ya = Y[i], yb = Y[i + 1];
    if (yb - ya < 1e-4) continue;
    const ym = (ya + yb) / 2;
    const cut = hs.filter((h) => h.y0 <= ym && h.y1 >= ym).sort((p, q) => p.t0 - q.t0);
    const att = split && ym > split.y ? split.a : a;
    let t = t0;
    for (const h of cut) { if (h.t0 > t) wallRect(b, side, c, t, h.t0, ya, yb, att, face, vOff); t = Math.max(t, h.t1); }
    if (t < t1) wallRect(b, side, c, t, t1, ya, yb, att, face, vOff);
  }
}
/** Jambs, head and sill of an opening, from a wall plane `d0`..`d1` outward. */
function reveal(b: GeoBuilder, side: Side, c: number, h: { t0: number; t1: number; y0: number; y1: number }, d0: number, d1: number, a: Attr, sill: Attr | null) {
  const n = outward(side);
  const tdir: V3 = side === 'n' || side === 's' ? [1, 0, 0] : [0, 0, 1];
  const P = (t: number, y: number, d: number) => onPlane(side, c, t, y, d);
  quadFacing(b, [P(h.t0, h.y0, d0), P(h.t0, h.y0, d1), P(h.t0, h.y1, d1), P(h.t0, h.y1, d0)], a, tdir);
  quadFacing(b, [P(h.t1, h.y0, d0), P(h.t1, h.y0, d1), P(h.t1, h.y1, d1), P(h.t1, h.y1, d0)], a, [-tdir[0], 0, -tdir[2]]);
  quadFacing(b, [P(h.t0, h.y1, d0), P(h.t1, h.y1, d0), P(h.t1, h.y1, d1), P(h.t0, h.y1, d1)], a, [0, -1, 0]);
  if (sill) quadFacing(b, [P(h.t0, h.y0, d0), P(h.t1, h.y0, d0), P(h.t1, h.y0, d1), P(h.t0, h.y0, d1)], sill, [0, 1, 0]);
  void n;
}
function hash(s: string): number { let h = 2166136261; for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619); return ((h >>> 0) % 100000) / 100000; }

// ---------------------------------------------------------------- facade planes
function facadePlanes(plan: BuildingPlan): Plane[] {
  const planes: Plane[] = [];
  const W = plan.wings;
  W.forEach((w, wi) => {
    const sides: [Side, number, number, number][] = [['n', w.z0, w.x0, w.x1], ['s', w.z1, w.x0, w.x1], ['w', w.x0, w.z0, w.z1], ['e', w.x1, w.z0, w.z1]];
    for (const [side, c, a0, a1] of sides) {
      // subtract the parts covered by a neighbouring wing
      let spans: [number, number][] = [[a0, a1]];
      W.forEach((o, oi) => {
        if (oi === wi) return;
        const px = side === 'n' ? c - 0.2 : side === 's' ? c + 0.2 : 0, pz = px;
        void pz;
        let cov: [number, number] | null = null;
        if (side === 'n' || side === 's') { const z = side === 'n' ? c - 0.2 : c + 0.2; if (z > o.z0 && z < o.z1) cov = [o.x0, o.x1]; }
        else { const x = side === 'w' ? c - 0.2 : c + 0.2; if (x > o.x0 && x < o.x1) cov = [o.z0, o.z1]; }
        if (!cov) return;
        const out: [number, number][] = [];
        for (const [s0, s1] of spans) { if (cov[1] <= s0 || cov[0] >= s1) { out.push([s0, s1]); continue; } if (cov[0] > s0) out.push([s0, cov[0]]); if (cov[1] < s1) out.push([cov[1], s1]); }
        spans = out;
      });
      for (const [s0, s1] of spans) if (s1 - s0 > 0.05) planes.push({ side, c, t0: s0, t1: s1, holes: [] });
    }
  });
  // assign exterior openings to the plane they sit in
  for (const room of plan.rooms) for (const o of room.openings) {
    if (!o.exterior) continue;
    const R = room.rect;
    const c = o.side === 'n' ? R.z0 - EXT : o.side === 's' ? R.z1 + EXT : o.side === 'w' ? R.x0 - EXT : R.x1 + EXT;
    const pl = planes.find((p) => p.side === o.side && Math.abs(p.c - c) < 0.12 && o.t0 >= p.t0 - 0.05 && o.t1 <= p.t1 + 0.05);
    if (pl) pl.holes.push({ t0: o.t0, t1: o.t1, y0: room.y + o.y0, y1: room.y + o.y1, kind: o.kind, room, o });
  }
  return planes;
}

export interface BuildOpts { near: boolean }

/** The exterior of one building into `b` (opaque) and `g` (glass, near only). */
export function buildExterior(plan: BuildingPlan, b: GeoBuilder, g: GeoBuilder | null, opts: BuildOpts) {
  const r = rngFor('mesh', plan.id);
  const near = opts.near;
  const block = plan.kind === 'block';
  const house = plan.kind === 'house';
  const st = plan.style;
  const wallCol = house || plan.kind === 'church' ? HOUSE[Math.floor(hash(plan.id) * HOUSE.length)] : st.panel;
  const wallA: Attr = st.wall === 'panel' ? A(wallCol, M.PANEL, { seed: r(), aux: [block ? 3.0 : 3.6, block ? 2.75 : 3.5] })
    : st.wall === 'brick' ? A(r() < 0.5 ? '#7a4a36' : '#8a5a42', M.BRICK, { seed: r() }) : A(wallCol, M.PLASTER, { seed: r() });
  const plinthA = A('#6e6a62', M.CONCRETE, { seed: r() });
  const frameCol = lin(st.frame);
  const f0 = plan.floorY[0];
  const top = plan.height;
  const parapet = house ? 0 : block ? 0.9 : 0.5;
  const planes = facadePlanes(plan);
  const vOff = f0;

  // ---------------- facades
  for (const pl of planes) {
    const holes = pl.holes.map((h) => ({ t0: h.t0, t1: h.t1, y0: h.y0, y1: h.y1 }));
    wallWithHoles(b, pl.side, pl.c, pl.t0, pl.t1, -0.3, top + parapet, holes, wallA, 1, vOff, { y: -1, a: wallA });
    // plinth band: a darker skirt up to the ground floor
    if (f0 > 0.2) wallWithHoles(b, pl.side, pl.c, pl.t0, pl.t1, -0.3, f0, holes, plinthA, 1, 0);
    // a mosaic or painted band at the top of the blocks
    if (block) {
      const n = outward(pl.side);
      b.push().translate(n[0] * 0.04, 0, n[2] * 0.04);
      wallRect(b, pl.side, pl.c, pl.t0, pl.t1, top - 0.05, top + parapet, st.parapet === 'mosaic' ? A(st.accent, M.MOSAIC, { seed: r() }) : withA(wallA, { col: tint(wallA, 0.9).col }), 1);
      b.pop();
      // parapet cap
      const cap = A('#7a7770', M.CONCRETE, { snow: 1 });
      const p0 = onPlane(pl.side, pl.c, pl.t0, top + parapet, 0.06), p1 = onPlane(pl.side, pl.c, pl.t1, top + parapet, 0.06);
      const q0 = onPlane(pl.side, pl.c, pl.t0, top + parapet, -0.2), q1 = onPlane(pl.side, pl.c, pl.t1, top + parapet, -0.2);
      quadFacing(b, [p0, p1, q1, q0], cap, [0, 1, 0]);
      // inner face of the parapet
      b.push(); const ni = outward(pl.side); b.translate(-ni[0] * 0.2, 0, -ni[2] * 0.2);
      wallRect(b, pl.side, pl.c, pl.t0, pl.t1, top, top + parapet, A('#77746c', M.CONCRETE), -1); b.pop();
    }
    // openings
    for (const h of pl.holes) {
      const n = outward(pl.side);
      const w = h.t1 - h.t0, hh = h.y1 - h.y0;
      const rev = A('#8a877e', M.CONCRETE, { seed: r() });
      const sillA = A('#5a5c58', M.METAL, { snow: 1 });
      const isDoor = h.kind === 'entrance' || h.kind === 'balcony';
      const lit = (h.room.lit ? 2 : 0) + (h.room.furniture.some((f) => f.type === 'tv' && f.on) ? 4 : 0);
      const seed = hash(h.room.id + h.t0) + lit;
      // outside window sill
      if (!isDoor && h.kind !== 'shopfront') {
        const s0 = onPlane(pl.side, pl.c, h.t0 - 0.04, h.y0 - 0.03, 0.09), s1 = onPlane(pl.side, pl.c, h.t1 + 0.04, h.y0 - 0.03, 0.09);
        const s2 = onPlane(pl.side, pl.c, h.t1 + 0.04, h.y0 - 0.03, 0), s3 = onPlane(pl.side, pl.c, h.t0 - 0.04, h.y0 - 0.03, 0);
        quadFacing(b, [s0, s1, s2, s3], sillA, [0, 1, 0]);
        quadFacing(b, [s0, s1, onPlane(pl.side, pl.c, h.t1 + 0.04, h.y0 - 0.08, 0.09), onPlane(pl.side, pl.c, h.t0 - 0.04, h.y0 - 0.08, 0.09)], sillA, n);
      }
      if (!near) {
        // far: the opening is a painted window with an interior behind it
        const mat = h.kind === 'shopfront' ? M.SHOP : M.WIN;
        if (h.kind === 'entrance') {
          reveal(b, pl.side, pl.c, h, 0, -0.18, rev, null);
          wallRect(b, pl.side, pl.c - (pl.side === 'n' || pl.side === 'w' ? -0.18 : 0.18), h.t0, h.t1, h.y0, h.y1, A(h.room.type === 'lobby' ? '#4a3a2a' : '#3e4a3e', M.WOOD, { seed: r() }), 1);
          continue;
        }
        const p = [onPlane(pl.side, pl.c, h.t0, h.y0, 0.005), onPlane(pl.side, pl.c, h.t1, h.y0, 0.005), onPlane(pl.side, pl.c, h.t1, h.y1, 0.005), onPlane(pl.side, pl.c, h.t0, h.y1, 0.005)];
        // uv: metres from the bottom-left corner as seen from outside
        const sgn = pl.side === 's' || pl.side === 'w' ? 1 : -1;
        const uvs: [number, number][] = sgn > 0 ? [[0, 0], [w, 0], [w, hh], [0, hh]] : [[w, 0], [0, 0], [0, hh], [w, hh]];
        quadFacing(b, p, A(frameCol, mat, { seed, aux: [w, hh] }), n, uvs);
      } else {
        // near: a real opening — reveal through the wall, frame and glass
        const depth = EXT;
        reveal(b, pl.side, pl.c, h, 0, -depth, rev, isDoor ? null : A('#c8c4b8', M.PAINT, {}));
        if (h.kind === 'entrance') { entranceDoor(b, pl.side, pl.c, h, r); continue; }
        windowFrame(b, g!, pl.side, pl.c, h, frameCol, h.kind === 'shopfront');
      }
    }
  }

  // ---------------- roofs
  for (const w of plan.wings) {
    if (house && w === plan.wings[0]) pitchedRoof(b, w, top, st.roof === 'tile' ? A('#7a3a26', M.TILE, { seed: r(), snow: 1 }) : A('#6a6a64', M.TINROOF, { seed: r(), snow: 1 }), wallA);
    else if (house) b.flat(w.x0 - 0.2, w.z0 - 0.2, w.x1 + 0.2, w.z1 + 0.2, top + 0.02, A('#5a5a54', M.TINROOF, { seed: r(), snow: 1 }));
    else {
      b.flat(w.x0, w.z0, w.x1, w.z1, top, A('#4a4844', M.ROOFFLAT, { seed: r(), snow: 1 }));
      if (near) b.flat(w.x0 + EXT, w.z0 + EXT, w.x1 - EXT, w.z1 - EXT, top - 0.02, A('#d8d4c8', M.PLAIN), true);
    }
  }
  if (block) roofKit(b, plan, r);

  // ---------------- balconies
  for (const bal of plan.balconies) balcony(b, plan, bal, r, wallA);

  // ---------------- entrance steps and canopies
  for (const s of exteriorSteps(plan)) {
    const conc = A('#7e7b74', M.CONCRETE, { seed: r(), snow: 1 });
    const n = s.steps;
    for (let i = 0; i < n; i++) {
      const y1 = ((i + 1) / n) * s.rise;
      // steps from the door outward: step i is lower the further out it is
      const d0 = s.depth * (1 - (i + 1) / n), d1 = s.depth * (1 - i / n);
      const P = (t: number, y: number, d: number) => onPlane(s.side, s.c, t, y, d);
      const x0 = s.t0, x1 = s.t1;
      const pts = [P(x0, -0.2, d0), P(x1, -0.2, d0), P(x1, -0.2, d1), P(x0, -0.2, d1)];
      void pts;
      const bx = boxOnPlane(s.side, s.c, x0, x1, -0.2, y1, d0, d1);
      b.boxMM(bx[0], bx[1], bx[2], bx[3], bx[4], bx[5], conc, { ny: false });
    }
    // canopy over the door
    if (s.canopy) {
      const cb = boxOnPlane(s.side, s.c, s.t0 - 0.4, s.t1 + 0.4, s.rise + 2.45, s.rise + 2.6, 0, s.depth + 0.5);
      b.boxMM(cb[0], cb[1], cb[2], cb[3], cb[4], cb[5], A('#7a776e', M.CONCRETE, { snow: 1 }));
    }
  }

}

/** A furniture instance: which model, and where (column-major 4x4, building-local). */
export interface FurnInstance { key: string; item: FurnitureItem; lit: boolean; m: number[] }
const EMISSIVE = new Set(['lamp', 'bulb', 'tv', 'radio', 'stove']);
export function furnitureKey(it: FurnitureItem, room: Room): string {
  let k = `${it.type}:${it.variant}`;
  if (EMISSIVE.has(it.type)) k += `:${it.on ? 1 : 0}:${room.lit ? 1 : 0}`;
  if (it.w !== undefined || it.h !== undefined) k += `:${(it.w ?? 0).toFixed(1)}:${(it.h ?? 0).toFixed(1)}`;
  return k;
}
/** Model space version of an item (for building its shared geometry once). */
export function modelItem(it: FurnitureItem): FurnitureItem {
  return { type: it.type, x: 0, y: 0, z: 0, rot: 0, variant: it.variant, on: it.on, w: it.w !== undefined ? +it.w.toFixed(1) : undefined, h: it.h !== undefined ? +it.h.toFixed(1) : undefined };
}

/** One storey's rooms, stairs and landings into `b`; the furniture comes back as instances. */
export function buildFloor(plan: BuildingPlan, f: number, b: GeoBuilder): FurnInstance[] {
  const r = rngFor('mesh', plan.id, f);
  const out: FurnInstance[] = [];
  for (const room of plan.rooms) {
    if (room.floor !== f) continue;
    b.indoor = room.lit ? 2 : 1;
    interior(b, plan, room, r);
    for (const it of room.furniture) {
      const c = Math.cos(it.rot), s = Math.sin(it.rot);
      out.push({ key: furnitureKey(it, room), item: modelItem(it), lit: room.lit, m: [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, it.x, it.y, it.z, 1] });
    }
  }
  b.indoor = 1;
  const y0 = plan.floorY[f] - 0.01, y1 = f + 1 < plan.floorY.length ? plan.floorY[f + 1] - 0.01 : 1e9;
  stairsAndLandings(b, plan, r, (y) => y >= y0 && y < y1);
  b.indoor = 0;
  return out;
}

/** For a storey shown without its interior: interior-mapped panes in its window openings. */
export function buildPlugs(plan: BuildingPlan, f: number, b: GeoBuilder) {
  for (const room of plan.rooms) {
    if (room.floor !== f) continue;
    const R = room.rect;
    for (const o of room.openings) {
      if (!o.exterior) continue;
      const side = o.side as Side;
      const c = side === 'n' ? R.z0 - EXT : side === 's' ? R.z1 + EXT : side === 'w' ? R.x0 - EXT : R.x1 + EXT;
      const y0 = room.y + o.y0, y1 = room.y + o.y1, w = o.t1 - o.t0, hh = y1 - y0;
      const n = outward(side);
      if (o.kind === 'entrance') {
        const p = [onPlane(side, c, o.t0, y0, -EXT + 0.02), onPlane(side, c, o.t1, y0, -EXT + 0.02), onPlane(side, c, o.t1, y1, -EXT + 0.02), onPlane(side, c, o.t0, y1, -EXT + 0.02)];
        quadFacing(b, p, A('#3a2e22', M.WOOD, { seed: 0.4 }), n);
        continue;
      }
      const lit = (room.lit ? 2 : 0) + (room.furniture.some((it) => it.type === 'tv' && it.on) ? 4 : 0);
      const d = -0.2;
      const p = [onPlane(side, c, o.t0, y0, d), onPlane(side, c, o.t1, y0, d), onPlane(side, c, o.t1, y1, d), onPlane(side, c, o.t0, y1, d)];
      const sgn = side === 's' || side === 'w' ? 1 : -1;
      const uvs: [number, number][] = sgn > 0 ? [[0, 0], [w, 0], [w, hh], [0, hh]] : [[w, 0], [0, 0], [0, hh], [w, hh]];
      // +8 in the seed: a plug behind real glass, so no painted frame or reflection
      quadFacing(b, p, A('#c8c4b8', o.kind === 'shopfront' ? M.SHOP : M.WIN, { seed: hash(room.id + o.t0) + lit + 8, aux: [w, hh] }), n, uvs);
    }
  }
}

/** Box bounds for a slab in front of a wall plane: t0..t1 along, y0..y1, d0..d1 outward. */
function boxOnPlane(side: Side, c: number, t0: number, t1: number, y0: number, y1: number, d0: number, d1: number): number[] {
  const a = onPlane(side, c, t0, y0, d0), z = onPlane(side, c, t1, y1, d1);
  return [Math.min(a[0], z[0]), Math.min(a[1], z[1]), Math.min(a[2], z[2]), Math.max(a[0], z[0]), Math.max(a[1], z[1]), Math.max(a[2], z[2])];
}

function windowFrame(b: GeoBuilder, g: GeoBuilder, side: Side, c: number, h: Hole, frameCol: V3, shop: boolean) {
  const fa = A(frameCol, M.PAINT, { seed: 0.3 });
  const d = -0.12; // glass plane, inside the reveal
  const fw = shop ? 0.05 : 0.06;
  const w = h.t1 - h.t0;
  const bars: [number, number, number, number][] = [
    [h.t0, h.y0, h.t0 + fw, h.y1], [h.t1 - fw, h.y0, h.t1, h.y1], [h.t0, h.y0, h.t1, h.y0 + fw], [h.t0, h.y1 - fw, h.t1, h.y1],
  ];
  if (!shop && w > 0.95 && h.kind !== 'balcony') bars.push([(h.t0 + h.t1) / 2 - 0.035, h.y0, (h.t0 + h.t1) / 2 + 0.035, h.y1]);
  if (!shop && h.kind !== 'balcony') { const ty = h.y0 + (h.y1 - h.y0) * 0.74; bars.push([h.t0, ty - 0.03, h.t1, ty + 0.03]); }
  if (shop) { const ty = h.y0 + (h.y1 - h.y0) * 0.82; bars.push([h.t0, ty - 0.025, h.t1, ty + 0.025]); }
  for (const [t0, y0, t1, y1] of bars) {
    const bx = boxOnPlane(side, c, t0, t1, y0, y1, d - 0.03, d + 0.03);
    b.boxMM(bx[0], bx[1], bx[2], bx[3], bx[4], bx[5], fa);
  }
  // double glazing: two panes, as in every Romanian window
  for (const dd of [d + 0.02, d - 0.04]) {
    const p = [onPlane(side, c, h.t0, h.y0, dd), onPlane(side, c, h.t1, h.y0, dd), onPlane(side, c, h.t1, h.y1, dd), onPlane(side, c, h.t0, h.y1, dd)];
    quadFacing(g, p, A('#000000', M.GLASS, { seed: shop ? 1 : 0 }), outward(side));
  }
}

/** A vertical slab from ground point p0 toward p1 (local x along it), y0..y1 high, `th` thick. */
function slab(b: GeoBuilder, p0: V3, dir: V3, len: number, y0: number, y1: number, th: number, a: Attr, face?: Attr) {
  b.push().translate(p0[0], 0, p0[2]).rotateY(Math.atan2(-dir[2], dir[0]));
  b.boxMM(0, y0, -th / 2, len, y1, th / 2, a, face ? { pz: face, nz: face } : {});
  b.pop();
}
const tAxis = (side: Side): V3 => (side === 'n' || side === 's' ? [1, 0, 0] : [0, 0, 1]);

function entranceDoor(b: GeoBuilder, side: Side, c: number, h: Hole, r: () => number) {
  // double doors standing open into the lobby, so you can walk in
  const n = outward(side), T = tAxis(side);
  const leafA = A(h.room.type === 'lobby' ? '#5a4632' : '#3e4a3e', M.WOOD, { seed: r() });
  const half = (h.t1 - h.t0) / 2 - 0.01;
  const th = 1.35;
  for (const [t, s] of [[h.t0, 1], [h.t1, -1]] as const) {
    const hinge = onPlane(side, c, t, 0, -EXT + 0.03);
    const dir: V3 = [T[0] * s * Math.cos(th) - n[0] * Math.sin(th), 0, T[2] * s * Math.cos(th) - n[2] * Math.sin(th)];
    slab(b, hinge, dir, half, h.y0 + 0.01, h.y1 - 0.03, 0.045, leafA);
  }
}

function pitchedRoof(b: GeoBuilder, w: { x0: number; z0: number; x1: number; z1: number }, y: number, roofA: Attr, gableA: Attr) {
  const o = 0.45;
  const long = w.x1 - w.x0 >= w.z1 - w.z0;
  const span = long ? w.z1 - w.z0 : w.x1 - w.x0;
  const rise = Math.min(3.2, span * 0.42);
  if (long) {
    const zm = (w.z0 + w.z1) / 2;
    const a: V3 = [w.x0 - o, y - 0.2, w.z0 - o], bb: V3 = [w.x1 + o, y - 0.2, w.z0 - o], c: V3 = [w.x1 + o, y + rise, zm], d: V3 = [w.x0 - o, y + rise, zm];
    const e: V3 = [w.x1 + o, y - 0.2, w.z1 + o], f: V3 = [w.x0 - o, y - 0.2, w.z1 + o];
    const L = Math.hypot(rise + 0.2, (w.z1 - w.z0) / 2 + o);
    b.quad(bb, a, d, c, roofA, [[w.x1, 0], [w.x0, 0], [w.x0, L], [w.x1, L]]);
    b.quad(f, e, c, d, roofA, [[w.x0, 0], [w.x1, 0], [w.x1, L], [w.x0, L]]);
    b.quad(a, bb, c, d, A('#3a3028', M.WOOD), undefined);
    b.quad(e, f, d, c, A('#3a3028', M.WOOD), undefined);
    // gables
    for (const x of [w.x0, w.x1]) {
      const g0: V3 = [x, y, w.z0], g1: V3 = [x, y, w.z1], g2: V3 = [x, y + rise - 0.15, zm];
      const nx: V3 = [x === w.x0 ? -1 : 1, 0, 0];
      if (x === w.x0) b.tri(g0, g1, g2, nx, nx, nx, [w.z0, y], [w.z1, y], [zm, y + rise], gableA); else b.tri(g1, g0, g2, nx, nx, nx, [-w.z1, y], [-w.z0, y], [-zm, y + rise], gableA);
    }
  } else {
    const xm = (w.x0 + w.x1) / 2;
    const a: V3 = [w.x0 - o, y - 0.2, w.z1 + o], bb: V3 = [w.x0 - o, y - 0.2, w.z0 - o], c: V3 = [xm, y + rise, w.z0 - o], d: V3 = [xm, y + rise, w.z1 + o];
    const e: V3 = [w.x1 + o, y - 0.2, w.z0 - o], f: V3 = [w.x1 + o, y - 0.2, w.z1 + o];
    const L = Math.hypot(rise + 0.2, (w.x1 - w.x0) / 2 + o);
    b.quad(a, bb, c, d, roofA, [[w.z1, 0], [w.z0, 0], [w.z0, L], [w.z1, L]]);
    b.quad(e, f, d, c, roofA, [[w.z0, 0], [w.z1, 0], [w.z1, L], [w.z0, L]]);
    b.quad(bb, a, d, c, A('#3a3028', M.WOOD));
    b.quad(f, e, c, d, A('#3a3028', M.WOOD));
    for (const z of [w.z0, w.z1]) {
      const g0: V3 = [w.x0, y, z], g1: V3 = [w.x1, y, z], g2: V3 = [xm, y + rise - 0.15, z];
      const nz: V3 = [0, 0, z === w.z0 ? -1 : 1];
      if (z === w.z1) b.tri(g0, g1, g2, nz, nz, nz, [w.x0, y], [w.x1, y], [xm, y + rise], gableA); else b.tri(g1, g0, g2, nz, nz, nz, [-w.x1, y], [-w.x0, y], [-xm, y + rise], gableA);
    }
  }
}

/** Lift machine rooms, vent stacks and the forest of TV aerials on a block's roof. */
function roofKit(b: GeoBuilder, plan: BuildingPlan, r: () => number) {
  const y = plan.height;
  const conc = A('#86837a', M.CONCRETE, { seed: r(), snow: 1 });
  const metal = A('#5a5c5a', M.METAL, { seed: r() });
  const cores = plan.rooms.filter((rm) => rm.type === 'lobby');
  for (const c of cores) {
    const R = c.rect;
    if (plan.levels >= 9) b.boxMM(R.x0, y, R.z0, R.x1, y + 2.6, R.z1, conc);
    else b.boxMM(R.x0 + 0.3, y, R.z0 + 0.3, R.x0 + 1.3, y + 1.1, R.z0 + 1.1, conc);
  }
  for (const w of plan.wings) {
    const n = Math.floor(((w.x1 - w.x0) * (w.z1 - w.z0)) / 30);
    for (let i = 0; i < n; i++) {
      const x = w.x0 + 1 + r() * (w.x1 - w.x0 - 2), z = w.z0 + 1 + r() * (w.z1 - w.z0 - 2);
      const h = 1.8 + r() * 2.2;
      b.tube([x, y, z], [x, y + h, z], 0.02, 0.018, 4, metal, false);
      // a Yagi for TVR: boom with a few elements
      const ang = r() * Math.PI;
      const dx = Math.cos(ang), dz = Math.sin(ang);
      b.tube([x - dx * 0.6, y + h, z - dz * 0.6], [x + dx * 0.6, y + h, z + dz * 0.6], 0.012, 0.012, 3, metal, false);
      for (let k = -2; k <= 2; k++) {
        const cx = x + dx * k * 0.25, cz = z + dz * k * 0.25, l = 0.32 - Math.abs(k) * 0.03;
        b.tube([cx - dz * l, y + h, cz + dx * l], [cx + dz * l, y + h, cz - dx * l], 0.006, 0.006, 3, metal, false);
      }
    }
  }
}

function balcony(b: GeoBuilder, plan: BuildingPlan, bal: BuildingPlan['balconies'][number], r: () => number, wallA: Attr) {
  // find the facade plane through the room that opens onto it
  const room = plan.rooms.find((rm) => rm.floor === bal.floor && rm.openings.some((o) => o.kind === 'balcony' && o.side === bal.side && o.t0 >= bal.t0 - 0.1 && o.t1 <= bal.t1 + 0.1));
  if (!room) return;
  const R = room.rect;
  const side = bal.side as Side;
  const c = side === 'n' ? R.z0 - EXT : side === 's' ? R.z1 + EXT : side === 'w' ? R.x0 - EXT : R.x1 + EXT;
  const y = bal.y, D = bal.depth;
  const slab = A('#7e7b72', M.CONCRETE, { seed: r(), snow: 1 });
  const sb = boxOnPlane(side, c, bal.t0, bal.t1, y - 0.16, y, 0, D);
  b.boxMM(sb[0], sb[1], sb[2], sb[3], sb[4], sb[5], slab);
  const par = plan.style.parapet === 'mosaic' ? A(plan.style.accent, M.MOSAIC, { seed: r() }) : withA(wallA, {});
  const ph = 1.0;
  // front and side parapets
  const fb = boxOnPlane(side, c, bal.t0, bal.t1, y - 0.16, y + ph, D - 0.08, D);
  b.boxMM(fb[0], fb[1], fb[2], fb[3], fb[4], fb[5], par);
  for (const t of [bal.t0, bal.t1 - 0.08]) { const s = boxOnPlane(side, c, t, t + 0.08, y, y + ph, 0, D - 0.08); b.boxMM(s[0], s[1], s[2], s[3], s[4], s[5], par); }
  if (bal.enclosed) {
    // glazed in with whatever frames the tenant could find
    const fr = A(r() < 0.5 ? '#c8c2b0' : '#5a4a3a', M.PAINT, { seed: r() });
    const top = y + 2.45;
    const n = Math.max(2, Math.round((bal.t1 - bal.t0) / 0.7));
    for (let i = 0; i <= n; i++) { const t = bal.t0 + ((bal.t1 - bal.t0) * i) / n; const p = boxOnPlane(side, c, t - 0.025, t + 0.025, y + ph, top, D - 0.06, D - 0.01); b.boxMM(p[0], p[1], p[2], p[3], p[4], p[5], fr); }
    const tb = boxOnPlane(side, c, bal.t0, bal.t1, top - 0.05, top, 0, D);
    b.boxMM(tb[0], tb[1], tb[2], tb[3], tb[4], tb[5], fr);
    const gl = [onPlane(side, c, bal.t0, y + ph, D - 0.035), onPlane(side, c, bal.t1, y + ph, D - 0.035), onPlane(side, c, bal.t1, top, D - 0.035), onPlane(side, c, bal.t0, top, D - 0.035)];
    quadFacing(b, gl, A('#000000', M.GLASS), outward(side));
  }
  if (bal.laundry) {
    // two lines of washing between the side walls
    const cloth = ['#d8d4c8', '#8a9ab0', '#b07060', '#c8c0a0', '#6a7a5a', '#e0dcd0'];
    for (let k = 0; k < 2; k++) {
      const d = D - 0.25 - k * 0.35, yy = y + 1.75;
      let t = bal.t0 + 0.2;
      while (t < bal.t1 - 0.5) {
        const w = 0.3 + r() * 0.4, hh = 0.35 + r() * 0.45;
        const p = [onPlane(side, c, t, yy - hh, d), onPlane(side, c, t + w, yy - hh, d), onPlane(side, c, t + w, yy, d), onPlane(side, c, t, yy, d)];
        const a = A(cloth[Math.floor(r() * cloth.length)], M.CLOTH, { seed: r(), aux: [0, 1] });
        quadFacing(b, p, a, outward(side), [[0, 0], [w, 0], [w, 1], [0, 1]]);
        quadFacing(b, [p[1], p[0], p[3], p[2]], a, [-outward(side)[0], 0, -outward(side)[2]], [[w, 0], [0, 0], [0, 1], [w, 1]]);
        t += w + 0.05 + r() * 0.2;
      }
    }
  }
  if (bal.flag) {
    // a tricolour with the arms cut out, hung over the parapet
    const w = 1.2, hh = 0.8, t = (bal.t0 + bal.t1) / 2;
    const p = [onPlane(side, c, t - w / 2, y + ph - hh, D + 0.02), onPlane(side, c, t + w / 2, y + ph - hh, D + 0.02), onPlane(side, c, t + w / 2, y + ph, D + 0.02), onPlane(side, c, t - w / 2, y + ph, D + 0.02)];
    const sgn = side === 's' || side === 'w' ? 1 : -1;
    const a = A('#ffffff', M.FLAG, { seed: r(), aux: [w / hh, 0.4] });
    quadFacing(b, p, a, outward(side), sgn > 0 ? [[0, 0], [w / hh, 0], [w / hh, 1], [0, 1]] : [[w / hh, 0], [0, 0], [0, 1], [w / hh, 1]]);
  }
}

// ---------------------------------------------------------------- interiors
function subtractRect(R: { x0: number; z0: number; x1: number; z1: number }, H?: { x0: number; z0: number; x1: number; z1: number }) {
  if (!H || H.x1 <= R.x0 || H.x0 >= R.x1 || H.z1 <= R.z0 || H.z0 >= R.z1) return [R];
  const out = [];
  if (H.z0 > R.z0) out.push({ x0: R.x0, x1: R.x1, z0: R.z0, z1: H.z0 });
  if (H.z1 < R.z1) out.push({ x0: R.x0, x1: R.x1, z0: H.z1, z1: R.z1 });
  const z0 = Math.max(R.z0, H.z0), z1 = Math.min(R.z1, H.z1);
  if (H.x0 > R.x0) out.push({ x0: R.x0, x1: H.x0, z0, z1 });
  if (H.x1 < R.x1) out.push({ x0: H.x1, x1: R.x1, z0, z1 });
  return out;
}

function floorAttr(room: Room, plan: BuildingPlan): Attr {
  const s = (room.wallpaper + 0.5) / 8;
  switch (room.type) {
    case 'bath': case 'kitchen': return A(room.wallpaper % 2 ? '#8a7a6a' : '#6a6a6a', M.FLOORTILE, { seed: s });
    case 'stair': case 'lobby': case 'shop': case 'corridor': return A('#8a8478', M.TERRAZZO, { seed: s });
    case 'classroom': case 'office': return A('#6a5a42', M.LINO, { seed: s });
    case 'workshop': case 'garage': case 'storage': return A('#6a6862', M.CONCRETE, { seed: s });
    case 'nave': return A('#9a9282', M.FLOORTILE, { seed: s, aux: [1, 0] });
    case 'porch': return A('#7a6a5a', M.WOOD, { seed: s });
    default: return A(plan.kind === 'house' ? '#6a4a30' : '#7a5232', M.PARQUET, { seed: s, aux: [room.wallpaper % 3, 0] });
  }
}
function wallAttrs(room: Room): { a: Attr; split?: { y: number; a: Attr } } {
  const s = (room.wallpaper + 0.5) / 8;
  const white = A('#d8d4c6', M.PLAIN, { seed: s });
  switch (room.type) {
    case 'bath': return { a: A(room.wallpaper % 2 ? '#b8c4c8' : '#d0ccc0', M.WALLTILE, { seed: s }), split: { y: room.y + 1.6, a: A('#c8c8b8', M.OILPAINT, { seed: s }) } };
    case 'kitchen': return { a: A(room.wallpaper % 3 === 0 ? '#c8b890' : '#d4d0c4', M.WALLTILE, { seed: s }), split: { y: room.y + 1.5, a: A('#c4c0a8', M.OILPAINT, { seed: s }) } };
    case 'stair': case 'lobby': return { a: A(DADO[room.wallpaper % DADO.length], M.OILPAINT, { seed: s }), split: { y: room.y + 1.5, a: white } };
    case 'classroom': case 'office': case 'corridor': return { a: A('#6a7a6a', M.OILPAINT, { seed: s }), split: { y: room.y + 1.4, a: white } };
    case 'workshop': case 'garage': case 'storage': return { a: A('#8a8a82', M.CONCRETE, { seed: s }) };
    case 'shop': return { a: A('#a8b0a0', M.OILPAINT, { seed: s }) };
    case 'nave': return { a: A('#b8a888', M.PLASTER, { seed: s }) };
    default: return { a: A(WALLPAPER[room.wallpaper % WALLPAPER.length], M.WALLPAPER, { seed: s }) };
  }
}

function interior(b: GeoBuilder, plan: BuildingPlan, room: Room, r: () => number) {
  const R = room.rect;
  const y0 = room.y, y1 = room.y + room.h;
  // floor (with the stairwell cut out of it) and ceiling
  const fa = floorAttr(room, plan);
  for (const q of subtractRect(R, room.voidFloor)) b.flat(q.x0, q.z0, q.x1, q.z1, y0, fa);
  const ca = A(room.type === 'stair' || room.type === 'lobby' ? '#c8c4b8' : '#dcd8cc', M.PLAIN, { seed: r() });
  for (const q of subtractRect(R, room.voidCeil)) b.flat(q.x0, q.z0, q.x1, q.z1, y1, ca, true);
  const { a, split } = wallAttrs(room);
  const sides: [Side, number, number, number][] = [['n', R.z0, R.x0, R.x1], ['s', R.z1, R.x0, R.x1], ['w', R.x0, R.z0, R.z1], ['e', R.x1, R.z0, R.z1]];
  const skirting = A('#4a3a2a', M.WOOD, { seed: r() });
  for (const [side, c, t0, t1] of sides) {
    const ops = room.openings.filter((o) => o.side === side);
    const holes = ops.map((o) => ({ t0: o.t0, t1: o.t1, y0: y0 + o.y0, y1: y0 + o.y1 }));
    wallWithHoles(b, side, c, t0, t1, y0, y1, holes, a, -1, y0, split);
    // skirting board, broken by door openings
    if (room.type !== 'bath' && room.type !== 'kitchen' && room.type !== 'workshop' && room.type !== 'garage') {
      b.push(); const n = outward(side); b.translate(-n[0] * 0.012, 0, -n[2] * 0.012);
      wallWithHoles(b, side, c, t0, t1, y0, y0 + 0.08, holes.filter((h) => h.y0 <= y0 + 0.01), skirting, -1);
      b.pop();
    }
    // reveals: interior doors meet the neighbour's reveal in the middle of the partition
    for (const o of ops) {
      const h = { t0: o.t0, t1: o.t1, y0: y0 + o.y0, y1: y0 + o.y1 };
      const d = o.exterior ? EXT : INT / 2;
      const isDoor = o.kind === 'door' || o.kind === 'entrance' || o.kind === 'balcony';
      reveal(b, side, c, h, 0, d, A('#d0ccbe', M.PLAIN, {}), isDoor ? (o.exterior ? A('#7e7b74', M.CONCRETE) : null) : A('#cfcabb', M.PAINT));
      if (o.kind === 'door') {
        // door frame (toc) and, on one side only, the leaf standing open
        const fr = A(room.type === 'hall' && o.to?.includes('/r') && plan.rooms.find((x) => x.id === o.to)?.type === 'stair' ? '#5a3a24' : '#c8c0aa', M.PAINT, { seed: 0.2 });
        for (const t of [o.t0 - 0.05, o.t1]) { const bx = boxOnPlane(side, c, t, t + 0.05, y0, y0 + o.y1 + 0.05, -0.015, 0.0); b.boxMM(bx[0], bx[1], bx[2], bx[3], bx[4], bx[5], fr); }
        const hb = boxOnPlane(side, c, o.t0 - 0.05, o.t1 + 0.05, y0 + o.y1, y0 + o.y1 + 0.06, -0.015, 0); b.boxMM(hb[0], hb[1], hb[2], hb[3], hb[4], hb[5], fr);
        if (side === 'n' || side === 'w') doorLeaf(b, side, c, o, y0, room, plan);
      }
    }
  }
}

function doorLeaf(b: GeoBuilder, side: Side, c: number, o: Opening, y0: number, room: Room, plan: BuildingPlan) {
  const other = plan.rooms.find((x) => x.id === o.to);
  const front = other?.type === 'stair' || room.type === 'stair';
  // flat front doors are padded brown leatherette; inner doors are cream with a frosted panel
  const leaf = front ? A('#4a2e1e', M.UPHOLSTERY, { seed: 0.5 }) : A('#d4ccb4', M.PAINT, { seed: 0.4 });
  const n = outward(side), T = tAxis(side);
  const w = o.t1 - o.t0 - 0.02, hgt = o.y1 - 0.03;
  // hinged at t0, swung ~85° into this room
  const hinge = onPlane(side, c, o.t0 + 0.01, 0, -0.03);
  const th = 1.48;
  const dir: V3 = [T[0] * Math.cos(th) - n[0] * Math.sin(th), 0, T[2] * Math.cos(th) - n[2] * Math.sin(th)];
  slab(b, hinge, dir, w, y0 + 0.01, y0 + hgt, 0.04, leaf);
  if (!front) {
    const p0: V3 = [hinge[0] + dir[0] * 0.15, 0, hinge[2] + dir[2] * 0.15];
    slab(b, p0, dir, w - 0.3, y0 + hgt * 0.45, y0 + hgt - 0.15, 0.046, A('#a8a898', M.LACE, { seed: 0.3 }));
  }
  const kn: V3 = [hinge[0] + dir[0] * (w - 0.1), 0, hinge[2] + dir[2] * (w - 0.1)];
  b.box(kn[0], y0 + 1.0, kn[2], 0.05, 0.05, 0.12, A('#9a9488', M.CHROME));
}

function stairsAndLandings(b: GeoBuilder, plan: BuildingPlan, r: () => number, inBand: (y: number) => boolean) {
  const tread = A('#8a8478', M.TERRAZZO, { seed: r() });
  const soffit = A('#c8c4b6', M.PLAIN, { seed: r() });
  const rail = A('#3a3a36', M.METAL, { seed: r() });
  const hand = A(plan.kind === 'house' ? '#5a3a22' : '#2a2a28', plan.kind === 'house' ? M.WOOD : M.RUBBER, {});
  const house = plan.kind === 'house';
  for (const L of plan.landings) {
    if (!inBand(L.y)) continue;
    // landings at a storey's level are part of that room's floor
    if (plan.floorY.some((y) => Math.abs(y - L.y) < 0.01)) continue;
    b.boxMM(L.x0, L.y - 0.18, L.z0, L.x1, L.y, L.z1, tread, { py: tread, ny: soffit });
  }
  for (const f of plan.stairs) {
    if (!inBand(Math.min(f.yA, f.yB))) continue;
    const rise = f.yB - f.yA;
    const n = Math.max(2, Math.round(Math.abs(rise) / 0.17));
    const len = f.axis === 'z' ? f.z1 - f.z0 : f.x1 - f.x0;
    const ta = house ? A('#6a4a2e', M.WOOD, { seed: r() }) : tread;
    for (let i = 0; i < n; i++) {
      // step i spans [i/n, (i+1)/n] of the run; its top is at yA + rise*(i+1)/n
      const u0 = f.dir > 0 ? i / n : 1 - (i + 1) / n, u1 = f.dir > 0 ? (i + 1) / n : 1 - i / n;
      const yt = f.yA + (rise * (i + 1)) / n;
      const yb = Math.max(f.yA + (rise * i) / n - 0.22, f.yA - 0.2);
      if (f.axis === 'z') b.boxMM(f.x0, yb, f.z0 + len * u0, f.x1, yt, f.z0 + len * u1, ta, { ny: soffit });
      else b.boxMM(f.x0 + len * u0, yb, f.z0, f.x0 + len * u1, yt, f.z1, ta, { ny: soffit });
    }
    // railing on the open side of block stairs: balusters and a handrail
    if (!house && plan.kind !== 'church') {
      const cx = (f.x0 + f.x1) / 2, cz = (f.z0 + f.z1) / 2;
      // the open side is toward the stair core's centre line: pick the edge closer to the other flight
      const others = plan.stairs.filter((o) => o !== f && Math.abs((o.x0 + o.x1) / 2 - cx) < 3 && Math.abs((o.z0 + o.z1) / 2 - cz) < 3);
      if (!others.length) continue;
      const oc = others[0];
      const ex = f.axis === 'z' ? ((oc.x0 + oc.x1) / 2 > cx ? f.x1 - 0.03 : f.x0 + 0.03) : 0;
      const ez = f.axis === 'x' ? ((oc.z0 + oc.z1) / 2 > cz ? f.z1 - 0.03 : f.z0 + 0.03) : 0;
      const P = (u: number, y: number): V3 => (f.axis === 'z' ? [ex, y, f.z0 + len * u] : [f.x0 + len * u, y, ez]);
      const yAt = (u: number) => (f.dir > 0 ? f.yA + rise * u : f.yA + rise * (1 - u));
      for (let i = 0; i <= n; i += 2) { const u = Math.min(1, (i + 0.5) / n); const y = yAt(u); b.tube(P(u, y), P(u, y + 0.9), 0.009, 0.009, 4, rail, false); }
      b.tube(P(0, yAt(0) + 0.92), P(1, yAt(1) + 0.92), 0.025, 0.025, 6, hand, true);
    }
  }
}
