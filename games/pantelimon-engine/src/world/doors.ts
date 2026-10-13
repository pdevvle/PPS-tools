// ===================================================================
// Door leaves from a building plan, in building-local metres: where each
// leaf is hinged, which way it lies when shut and which way it swings.
// Pure data (part of the port format): the runtime animates the angle.
//   inner   cream panel door with a frosted pane, between rooms of a flat
//   front   a flat's front door, padded brown leatherette, on the landing
//   lobby   double wooden doors with glass at a block's entrance
//   house   a plank door with a small window
//   shop    a glazed aluminium door
//   garage  an up-and-over steel door (tilts up instead of swinging)
//   works   double steel doors on a workshop
// ===================================================================
import type { BuildingPlan, Opening, Room } from '../data/schema';
import { EXT } from './extras';

export type DoorKind = 'inner' | 'front' | 'lobby' | 'house' | 'shop' | 'garage' | 'works';
export interface DoorSpec {
  id: string; kind: DoorKind; floor: number;
  hinge: [number, number, number];   // hinge foot (garage: the bottom corner under the top hinge)
  w: number; h: number;
  closed: [number, number];          // unit direction from the hinge along the shut leaf
  open: [number, number];            // unit direction the leaf swings toward (into the room)
  max: number;                       // how far it opens, radians
  lit: boolean;                      // the room it opens into has the light on
}
type Side = 'n' | 's' | 'e' | 'w';
const outward = (s: Side): [number, number] => (s === 'n' ? [0, -1] : s === 's' ? [0, 1] : s === 'w' ? [-1, 0] : [1, 0]);
const along = (s: Side): [number, number] => (s === 'n' || s === 's' ? [1, 0] : [0, 1]);
function planePoint(side: Side, c: number, t: number, d: number): [number, number] {
  return side === 'n' ? [t, c - d] : side === 's' ? [t, c + d] : side === 'w' ? [c - d, t] : [c + d, t];
}
function wallC(room: Room, side: Side): number {
  const R = room.rect;
  return side === 'n' ? R.z0 : side === 's' ? R.z1 : side === 'w' ? R.x0 : R.x1;
}

const PASSAGE = new Set(['hall', 'stair', 'lobby', 'corridor']);
/** Would a leaf swung open from (hx, hz) toward `into` cross a stair flight? */
function hitsStairs(plan: BuildingPlan, y: number, hx: number, hz: number, into: [number, number], w: number): boolean {
  const ex = hx + into[0] * w, ez = hz + into[1] * w;
  for (const f of plan.stairs) {
    if (Math.min(f.yA, f.yB) > y + 0.5 || Math.max(f.yA, f.yB) < y - 0.5) continue;
    const x0 = f.x0 - 0.15, x1 = f.x1 + 0.15, z0 = f.z0 - 0.15, z1 = f.z1 + 0.15;
    for (let k = 0; k <= 6; k++) { const x = hx + (ex - hx) * (k / 6), z = hz + (ez - hz) * (k / 6); if (x > x0 && x < x1 && z > z0 && z < z1) return true; }
  }
  return false;
}

export function doorsFromPlan(plan: BuildingPlan, floor?: number): DoorSpec[] {
  const out: DoorSpec[] = [];
  const byId = new Map(plan.rooms.map((r) => [r.id, r] as const));
  const seen = new Set<string>();
  for (const room of plan.rooms) {
    if (floor !== undefined && room.floor !== floor) continue;
    room.openings.forEach((o: Opening, oi) => {
      const side = o.side as Side;
      const n = outward(side), T = along(side);
      const into: [number, number] = [-n[0], -n[1]];
      const y = room.y;
      if (o.kind === 'door') {
        // one leaf per doorway. Doors open into rooms, not into the hall or the stairwell
        // (a flat's front door opens into its own hall); between two rooms, the north or west one
        const other = o.to ? byId.get(o.to) : undefined;
        const pairKey = [room.id, o.to].sort().join('|');
        if (seen.has(pairKey)) return;
        const front = room.type === 'stair' || room.type === 'lobby' || other?.type === 'stair' || other?.type === 'lobby';
        let mine: boolean;
        if (front) mine = room.type === 'hall' || (other?.type !== 'hall' && (side === 'n' || side === 'w'));
        else if (PASSAGE.has(room.type) !== PASSAGE.has(other?.type ?? '')) mine = !PASSAGE.has(room.type);
        else mine = side === 'n' || side === 'w';
        if (!mine) return;
        seen.add(pairKey);
        const w = o.t1 - o.t0 - 0.02;
        // hinge on whichever side keeps the open leaf clear of stairs
        let t = o.t0 + 0.01, closed: [number, number] = T;
        let [hx, hz] = planePoint(side, wallC(room, side), t, -0.03);
        if (hitsStairs(plan, y, hx, hz, into, w)) { t = o.t1 - 0.01; closed = [-T[0], -T[1]]; [hx, hz] = planePoint(side, wallC(room, side), t, -0.03); }
        out.push({ id: `${room.id}/d${oi}`, kind: front ? 'front' : 'inner', floor: room.floor, hinge: [hx, y, hz], w, h: o.y1 - 0.03, closed, open: into, max: 1.5, lit: room.lit });
        return;
      }
      if (o.kind !== 'entrance' || !o.exterior) return;
      // street doors sit at the inner face of the outside wall and open inward
      const c = wallC(room, side) + (side === 'n' || side === 'w' ? -EXT : EXT);
      const d = -EXT + 0.03;
      const w = o.t1 - o.t0, h = o.y1 - o.y0 - 0.03;
      const id = `${room.id}/e${oi}`;
      const lit = room.lit;
      if (room.type === 'garage') {
        const [hx, hz] = planePoint(side, c, o.t0 + 0.02, d);
        out.push({ id, kind: 'garage', floor: room.floor, hinge: [hx, y, hz], w: w - 0.04, h: h, closed: T, open: into, max: 1.45, lit });
        return;
      }
      const kind: DoorKind = room.type === 'lobby' ? 'lobby' : room.type === 'shop' ? 'shop' : room.type === 'workshop' ? 'works' : room.type === 'classroom' || room.type === 'office' || room.type === 'nave' ? 'lobby' : 'house';
      if (w >= 1.25) {
        const half = w / 2 - 0.015;
        const [ax, az] = planePoint(side, c, o.t0 + 0.01, d), [bx, bz] = planePoint(side, c, o.t1 - 0.01, d);
        out.push({ id: id + 'a', kind, floor: room.floor, hinge: [ax, y, az], w: half, h, closed: T, open: into, max: 1.4, lit });
        out.push({ id: id + 'b', kind, floor: room.floor, hinge: [bx, y, bz], w: half, h, closed: [-T[0], -T[1]], open: into, max: 1.4, lit });
      } else {
        let [hx, hz] = planePoint(side, c, o.t0 + 0.01, d);
        let closed: [number, number] = T;
        if (hitsStairs(plan, y, hx, hz, into, w)) { [hx, hz] = planePoint(side, c, o.t1 - 0.01, d); closed = [-T[0], -T[1]]; }
        out.push({ id, kind, floor: room.floor, hinge: [hx, y, hz], w: w - 0.02, h, closed, open: into, max: 1.5, lit });
      }
    });
  }
  return out;
}
