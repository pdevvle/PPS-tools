// ===================================================================
// Collision geometry from a building plan, in building-local metres:
// wall segments with a height range (doorways cut out), walkable floor
// rectangles (stairwells cut out) and sloped stair flights. Pure data,
// so a port can use the same walls.
// ===================================================================
import type { BuildingPlan, Room } from '../data/schema';
import { exteriorSteps, EXT } from './extras';

export interface Seg { ax: number; az: number; bx: number; bz: number; y0: number; y1: number }
export interface Rect { x0: number; z0: number; x1: number; z1: number; y: number }
export interface Slope { x0: number; z0: number; x1: number; z1: number; yA: number; yB: number; axis: 'x' | 'z'; dir: 1 | -1 }
export interface PlanCollision { segs: Seg[]; rects: Rect[]; slopes: Slope[] }

type Side = 'n' | 's' | 'e' | 'w';
const along = (side: Side, c: number, t0: number, t1: number, y0: number, y1: number): Seg =>
  side === 'n' || side === 's' ? { ax: t0, az: c, bx: t1, bz: c, y0, y1 } : { ax: c, az: t0, bx: c, bz: t1, y0, y1 };

function cut(spans: [number, number][], a: number, b: number): [number, number][] {
  const out: [number, number][] = [];
  for (const [s0, s1] of spans) { if (b <= s0 || a >= s1) { out.push([s0, s1]); continue; } if (a > s0) out.push([s0, a]); if (b < s1) out.push([b, s1]); }
  return out;
}
function minus(r: { x0: number; z0: number; x1: number; z1: number }, h?: { x0: number; z0: number; x1: number; z1: number }) {
  if (!h || h.x1 <= r.x0 || h.x0 >= r.x1 || h.z1 <= r.z0 || h.z0 >= r.z1) return [r];
  const out = [];
  if (h.z0 > r.z0) out.push({ x0: r.x0, x1: r.x1, z0: r.z0, z1: h.z0 });
  if (h.z1 < r.z1) out.push({ x0: r.x0, x1: r.x1, z0: h.z1, z1: r.z1 });
  const z0 = Math.max(r.z0, h.z0), z1 = Math.min(r.z1, h.z1);
  if (h.x0 > r.x0) out.push({ x0: r.x0, x1: h.x0, z0, z1 });
  if (h.x1 < r.x1) out.push({ x0: h.x1, x1: r.x1, z0, z1 });
  return out;
}
const passable = (k: string) => k === 'door' || k === 'entrance' || k === 'balcony';

export function collisionFromPlan(plan: BuildingPlan): PlanCollision {
  const segs: Seg[] = [], rects: Rect[] = [], slopes: Slope[] = [];
  const top = plan.height + 1.2;
  // ---- room walls and floors
  for (const room of plan.rooms) roomWalls(room, segs);
  for (const room of plan.rooms) for (const q of minus(room.rect, room.voidFloor)) rects.push({ ...q, y: room.y });
  // ---- the facade, storey by storey, open only at entrances and balcony doors
  const W = plan.wings;
  const bands: [number, number][] = [[-2, plan.floorY[0]], ...plan.floorY.map((y, f) => [y, f + 1 < plan.floorY.length ? plan.floorY[f + 1] : top] as [number, number])];
  W.forEach((w, wi) => {
    const sides: [Side, number, number, number][] = [['n', w.z0, w.x0, w.x1], ['s', w.z1, w.x0, w.x1], ['w', w.x0, w.z0, w.z1], ['e', w.x1, w.z0, w.z1]];
    for (const [side, c, a0, a1] of sides) {
      let spans: [number, number][] = [[a0, a1]];
      W.forEach((o, oi) => {
        if (oi === wi) return;
        if (side === 'n' || side === 's') { const z = side === 'n' ? c - 0.2 : c + 0.2; if (z > o.z0 && z < o.z1) spans = cut(spans, o.x0, o.x1); }
        else { const x = side === 'w' ? c - 0.2 : c + 0.2; if (x > o.x0 && x < o.x1) spans = cut(spans, o.z0, o.z1); }
      });
      for (const [b0, b1] of bands) {
        let s = spans.slice();
        for (const room of plan.rooms) {
          if (room.y < b0 - 0.01 || room.y >= b1 - 0.01) continue;
          for (const o of room.openings) {
            if (!o.exterior || o.side !== side || !passable(o.kind)) continue;
            const R = room.rect;
            const oc = side === 'n' ? R.z0 - EXT : side === 's' ? R.z1 + EXT : side === 'w' ? R.x0 - EXT : R.x1 + EXT;
            if (Math.abs(oc - c) > 0.15) continue;
            s = cut(s, o.t0, o.t1);
          }
        }
        for (const [t0, t1] of s) segs.push(along(side, c, t0, t1, b0, b1));
      }
    }
  });
  // ---- landings and stair flights
  for (const L of plan.landings) rects.push({ ...L });
  for (const f of plan.stairs) {
    slopes.push({ ...f });
    // a railing between switchback flights so you can't hop across
    const i = plan.stairs.indexOf(f);
    const adj = plan.stairs.find((o, j) => j > i && o.axis === f.axis && (f.axis === 'z'
      ? Math.abs(o.z0 - f.z0) < 0.05 && Math.abs(o.z1 - f.z1) < 0.05 && Math.min(Math.abs(o.x0 - f.x1), Math.abs(f.x0 - o.x1)) < 0.3
      : Math.abs(o.x0 - f.x0) < 0.05 && Math.abs(o.x1 - f.x1) < 0.05 && Math.min(Math.abs(o.z0 - f.z1), Math.abs(f.z0 - o.z1)) < 0.3));
    if (adj) {
      const lo = Math.min(f.yA, f.yB, adj.yA, adj.yB) + 0.4, hi = Math.max(f.yA, f.yB, adj.yA, adj.yB) + 1.1;
      if (f.axis === 'z') { const x = (Math.max(f.x0, adj.x0) + Math.min(f.x1, adj.x1)) / 2; segs.push({ ax: x, az: f.z0 + 0.2, bx: x, bz: f.z1 - 0.2, y0: lo, y1: hi }); }
      else { const z = (Math.max(f.z0, adj.z0) + Math.min(f.z1, adj.z1)) / 2; segs.push({ ax: f.x0 + 0.2, az: z, bx: f.x1 - 0.2, bz: z, y0: lo, y1: hi }); }
    }
  }
  // ---- steps up to the entrances
  for (const s of exteriorSteps(plan)) {
    const P = (t: number, d: number): [number, number] => (s.side === 'n' ? [t, s.c - d] : s.side === 's' ? [t, s.c + d] : s.side === 'w' ? [s.c - d, t] : [s.c + d, t]);
    const a = P(s.t0, 0), b = P(s.t1, s.depth);
    const axis = s.side === 'n' || s.side === 's' ? 'z' : 'x';
    const dir: 1 | -1 = s.side === 'n' || s.side === 'w' ? 1 : -1;
    slopes.push({ x0: Math.min(a[0], b[0]), z0: Math.min(a[1], b[1]), x1: Math.max(a[0], b[0]), z1: Math.max(a[1], b[1]), yA: 0, yB: s.rise, axis, dir });
  }
  // ---- balconies: a slab to stand on and a parapet
  for (const bal of plan.balconies) {
    const room = plan.rooms.find((rm) => rm.floor === bal.floor && rm.openings.some((o) => o.kind === 'balcony' && o.side === bal.side && o.t0 >= bal.t0 - 0.1 && o.t1 <= bal.t1 + 0.1));
    if (!room) continue;
    const R = room.rect, side = bal.side as Side;
    const c = side === 'n' ? R.z0 - EXT : side === 's' ? R.z1 + EXT : side === 'w' ? R.x0 - EXT : R.x1 + EXT;
    const out = side === 'n' || side === 'w' ? -1 : 1, D = bal.depth;
    const ns = side === 'n' || side === 's';
    const r = ns ? { x0: bal.t0, x1: bal.t1, z0: Math.min(c, c + out * D), z1: Math.max(c, c + out * D) } : { z0: bal.t0, z1: bal.t1, x0: Math.min(c, c + out * D), x1: Math.max(c, c + out * D) };
    rects.push({ ...r, y: bal.y });
    const y0 = bal.y, y1 = bal.y + 1.8;
    if (ns) { segs.push({ ax: bal.t0, az: c + out * (D - 0.05), bx: bal.t1, bz: c + out * (D - 0.05), y0, y1 }, { ax: bal.t0 + 0.04, az: c, bx: bal.t0 + 0.04, bz: c + out * D, y0, y1 }, { ax: bal.t1 - 0.04, az: c, bx: bal.t1 - 0.04, bz: c + out * D, y0, y1 }); }
    else { segs.push({ ax: c + out * (D - 0.05), az: bal.t0, bx: c + out * (D - 0.05), bz: bal.t1, y0, y1 }, { ax: c, az: bal.t0 + 0.04, bx: c + out * D, bz: bal.t0 + 0.04, y0, y1 }, { ax: c, az: bal.t1 - 0.04, bx: c + out * D, bz: bal.t1 - 0.04, y0, y1 }); }
  }
  return { segs, rects, slopes };
}

function roomWalls(room: Room, segs: Seg[]) {
  const R = room.rect, y0 = room.y, y1 = room.y + room.h;
  const sides: [Side, number, number, number][] = [['n', R.z0, R.x0, R.x1], ['s', R.z1, R.x0, R.x1], ['w', R.x0, R.z0, R.z1], ['e', R.x1, R.z0, R.z1]];
  for (const [side, c, a0, a1] of sides) {
    let spans: [number, number][] = [[a0, a1]];
    for (const o of room.openings) if (o.side === side && passable(o.kind)) spans = cut(spans, o.t0 + 0.03, o.t1 - 0.03);
    for (const [t0, t1] of spans) if (t1 - t0 > 0.01) segs.push(along(side, c, t0, t1, y0, y1));
  }
}

/** Height of a flight at a local point. */
export function slopeY(s: Slope, x: number, z: number): number {
  const u = s.axis === 'z' ? (z - s.z0) / (s.z1 - s.z0) : (x - s.x0) / (s.x1 - s.x0);
  const k = Math.min(1, Math.max(0, s.dir > 0 ? u : 1 - u));
  return s.yA + (s.yB - s.yA) * k;
}
