// ===================================================================
// Furniture: what a Bucharest flat, shop, classroom or workshop held in
// 1989, placed against walls, clear of doors, under or beside windows.
// Items are data (type, position, rotation, variant); the renderer turns
// each type into a model.
// ===================================================================
import type { BuildingPlan, FurnitureItem, Opening, Room } from '../data/schema';
import { rngFor, chance, pick, type Rng } from '../core/rng';

type Side = 'n' | 's' | 'e' | 'w';
export interface ItemDef { w: number; d: number; h: number; tall?: boolean; hang?: number; ceil?: boolean }

/** Footprint (w along the item's x, d along its z; the front faces +z) and height. `hang` = mounting height for wall items. */
export const FURNITURE: Record<string, ItemDef> = {
  wallunit: { w: 2.6, d: 0.45, h: 2.1, tall: true }, sofa: { w: 2.0, d: 0.86, h: 0.85 }, armchair: { w: 0.8, d: 0.8, h: 0.85 },
  coffeetable: { w: 1.0, d: 0.6, h: 0.5 }, tv: { w: 0.62, d: 0.5, h: 1.08 }, radio: { w: 0.56, d: 0.28, h: 0.32 },
  rug: { w: 2.4, d: 1.7, h: 0.012 }, wallcarpet: { w: 2.0, d: 0.03, h: 1.35, hang: 0.95 }, diningtable: { w: 1.2, d: 0.8, h: 0.75 },
  chair: { w: 0.44, d: 0.46, h: 0.92 }, plant: { w: 0.36, d: 0.36, h: 0.75 }, lamp: { w: 0.55, d: 0.55, h: 0.45, ceil: true },
  bed2: { w: 1.55, d: 2.0, h: 0.6 }, bed1: { w: 0.92, d: 2.0, h: 0.55 }, wardrobe: { w: 1.25, d: 0.6, h: 2.0, tall: true },
  dresser: { w: 1.0, d: 0.45, h: 0.8 }, nightstand: { w: 0.45, d: 0.4, h: 0.55 }, desk: { w: 1.1, d: 0.6, h: 0.75 },
  sink: { w: 0.8, d: 0.6, h: 0.88 }, stove: { w: 0.56, d: 0.6, h: 0.86 }, cupboard: { w: 0.6, d: 0.6, h: 0.88 },
  fridge: { w: 0.58, d: 0.6, h: 1.45, tall: true }, kitchentable: { w: 0.9, d: 0.65, h: 0.75 }, stool: { w: 0.34, d: 0.34, h: 0.46 },
  shelf: { w: 0.9, d: 0.24, h: 0.32, hang: 1.55 }, speaker: { w: 0.3, d: 0.12, h: 0.26, hang: 1.85 },
  tub: { w: 1.55, d: 0.72, h: 0.56 }, basin: { w: 0.52, d: 0.42, h: 0.86 }, toilet: { w: 0.42, d: 0.66, h: 0.78 }, mirror: { w: 0.5, d: 0.03, h: 0.65, hang: 1.25 },
  coatrack: { w: 0.9, d: 0.32, h: 1.85, tall: true }, shoecabinet: { w: 0.8, d: 0.34, h: 0.88 }, phonetable: { w: 0.5, d: 0.4, h: 0.74 },
  shelves: { w: 1.2, d: 0.42, h: 2.0, tall: true }, crate: { w: 0.6, d: 0.42, h: 0.32 },
  shopcounter: { w: 2.4, d: 0.7, h: 0.95 }, shopshelf: { w: 1.8, d: 0.46, h: 2.2, tall: true }, scale: { w: 0.4, d: 0.3, h: 0.35 },
  schooldesk: { w: 1.1, d: 0.5, h: 0.76 }, teacherdesk: { w: 1.25, d: 0.62, h: 0.76 }, blackboard: { w: 2.8, d: 0.05, h: 1.2, hang: 0.9 },
  portraitshadow: { w: 0.62, d: 0.01, h: 0.82, hang: 1.95 }, filing: { w: 0.5, d: 0.6, h: 1.3, tall: true },
  lathe: { w: 1.9, d: 0.8, h: 1.25 }, workbench: { w: 2.0, d: 0.8, h: 0.9 }, barrel: { w: 0.6, d: 0.6, h: 0.9 },
  iconostasis: { w: 4.0, d: 0.3, h: 3.4, tall: true }, candlestand: { w: 0.5, d: 0.5, h: 1.1 }, bench: { w: 1.9, d: 0.45, h: 0.46 },
  car: { w: 1.64, d: 4.35, h: 1.45 }, tyres: { w: 0.62, d: 0.62, h: 0.8 },
  mailboxes: { w: 1.3, d: 0.16, h: 0.75, hang: 1.15 }, radiator: { w: 0.9, d: 0.1, h: 0.55, hang: 0.14 }, bulb: { w: 0.12, d: 0.12, h: 0.2, ceil: true },
  curtain: { w: 1.6, d: 0.05, h: 2.2 }, calendar: { w: 0.3, d: 0.01, h: 0.42, hang: 1.45 }, picture: { w: 0.5, d: 0.02, h: 0.4, hang: 1.6 },
  doorplate: { w: 0.14, d: 0.01, h: 0.06, hang: 1.55 }, ironingboard: { w: 1.2, d: 0.35, h: 0.85 }, sewingmachine: { w: 0.6, d: 0.45, h: 0.78 },
};

interface Placed { x0: number; z0: number; x1: number; z1: number }

class RoomFurnisher {
  occ: Placed[] = [];
  r: Rng;
  constructor(public room: Room) {
    this.r = rngFor('furnish', room.id);
    // keep the swing of every door clear
    for (const o of room.openings) if (o.kind === 'door' || o.kind === 'entrance' || o.kind === 'balcony') {
      const R = room.rect, dep = 0.95;
      if (o.side === 'n') this.occ.push({ x0: o.t0 - 0.1, x1: o.t1 + 0.1, z0: R.z0, z1: R.z0 + dep });
      if (o.side === 's') this.occ.push({ x0: o.t0 - 0.1, x1: o.t1 + 0.1, z0: R.z1 - dep, z1: R.z1 });
      if (o.side === 'w') this.occ.push({ x0: R.x0, x1: R.x0 + dep, z0: o.t0 - 0.1, z1: o.t1 + 0.1 });
      if (o.side === 'e') this.occ.push({ x0: R.x1 - dep, x1: R.x1, z0: o.t0 - 0.1, z1: o.t1 + 0.1 });
    }
  }
  get W() { return this.room.rect.x1 - this.room.rect.x0; }
  get D() { return this.room.rect.z1 - this.room.rect.z0; }
  free(p: Placed, ignoreDoor = false): boolean {
    const R = this.room.rect;
    if (p.x0 < R.x0 - 1e-3 || p.x1 > R.x1 + 1e-3 || p.z0 < R.z0 - 1e-3 || p.z1 > R.z1 + 1e-3) return false;
    return !this.occ.some((q, i) => (ignoreDoor && i < 0) || (p.x0 < q.x1 - 0.02 && p.x1 > q.x0 + 0.02 && p.z0 < q.z1 - 0.02 && p.z1 > q.z0 + 0.02));
  }
  /** The rotation and footprint of an item backed against a wall at position t. */
  wallPose(side: Side, t: number, def: ItemDef, gap = 0.02): { x: number; z: number; rot: number; fp: Placed } {
    const R = this.room.rect, hw = def.w / 2, d = def.d;
    switch (side) {
      case 'n': return { x: t, z: R.z0 + gap + d / 2, rot: 0, fp: { x0: t - hw, x1: t + hw, z0: R.z0, z1: R.z0 + gap + d } };
      case 's': return { x: t, z: R.z1 - gap - d / 2, rot: Math.PI, fp: { x0: t - hw, x1: t + hw, z0: R.z1 - gap - d, z1: R.z1 } };
      case 'w': return { x: R.x0 + gap + d / 2, z: t, rot: Math.PI / 2, fp: { x0: R.x0, x1: R.x0 + gap + d, z0: t - hw, z1: t + hw } };
      default: return { x: R.x1 - gap - d / 2, z: t, rot: -Math.PI / 2, fp: { x0: R.x1 - gap - d, x1: R.x1, z0: t - hw, z1: t + hw } };
    }
  }
  sideRange(side: Side): [number, number] {
    const R = this.room.rect;
    return side === 'n' || side === 's' ? [R.x0, R.x1] : [R.z0, R.z1];
  }
  /** Free spans along a wall for an item of this height (windows block tall things). */
  spans(side: Side, def: ItemDef): [number, number][] {
    let spans: [number, number][] = [this.sideRange(side)];
    const cut = (a: number, b: number) => {
      const out: [number, number][] = [];
      for (const [s0, s1] of spans) {
        if (b <= s0 || a >= s1) { out.push([s0, s1]); continue; }
        if (a > s0) out.push([s0, a]);
        if (b < s1) out.push([b, s1]);
      }
      spans = out;
    };
    for (const o of this.room.openings) {
      if (o.side !== side) continue;
      const blocks = o.kind === 'door' || o.kind === 'entrance' || o.kind === 'balcony' || o.kind === 'shopfront' ? true : (def.hang !== undefined ? def.hang + def.h > o.y0 - 0.05 && def.hang < o.y1 : def.h > o.y0 - 0.06);
      if (blocks) cut(o.t0 - 0.15, o.t1 + 0.15);
    }
    return spans.filter(([a, b]) => b - a >= def.w + 0.04);
  }
  add(type: string, x: number, y: number, z: number, rot: number, fp: Placed | null, extra: Partial<FurnitureItem> = {}): FurnitureItem {
    const it: FurnitureItem = { type, x: +x.toFixed(3), y: +y.toFixed(3), z: +z.toFixed(3), rot: +rot.toFixed(4), variant: Math.floor(this.r() * 4), ...extra };
    this.room.furniture.push(it);
    if (fp) this.occ.push(fp);
    return it;
  }
  /** Put an item against one of the given walls. where: 'center' of the longest span, 'corner', or 'any'. */
  wall(type: string, sides: Side[], where: 'center' | 'corner' | 'any' = 'any', opts: { y?: number; gap?: number } = {}): FurnitureItem | null {
    const def = FURNITURE[type];
    for (const side of sides) {
      const spans = this.spans(side, def).sort((a, b) => (b[1] - b[0]) - (a[1] - a[0]));
      for (const [a, b] of spans) {
        const tries = where === 'center' ? [(a + b) / 2] : where === 'corner' ? [a + def.w / 2 + 0.05, b - def.w / 2 - 0.05] : [(a + b) / 2, a + def.w / 2 + 0.05, b - def.w / 2 - 0.05, a + (b - a) * 0.3, a + (b - a) * 0.7];
        for (const t of tries) {
          const pose = this.wallPose(side, t, def, opts.gap ?? 0.02);
          if (def.hang !== undefined || this.free(pose.fp)) {
            const y = this.room.y + (opts.y ?? def.hang ?? 0);
            return this.add(type, pose.x, y, pose.z, pose.rot, def.hang !== undefined ? null : pose.fp);
          }
        }
      }
    }
    return null;
  }
  /** Free-standing item at a point, rotated. */
  at(type: string, x: number, z: number, rot: number, y?: number): FurnitureItem | null {
    const def = FURNITURE[type];
    const swap = Math.abs(Math.sin(rot)) > 0.7;
    const hw = (swap ? def.d : def.w) / 2, hd = (swap ? def.w : def.d) / 2;
    const fp = { x0: x - hw, x1: x + hw, z0: z - hd, z1: z + hd };
    if (!this.free(fp)) return null;
    return this.add(type, x, y ?? this.room.y, z, rot, def.h > 0.02 ? fp : null);
  }
  /** A point `dist` in front of a wall-placed item. */
  inFront(it: FurnitureItem, dist: number): [number, number] {
    return [it.x + Math.sin(it.rot) * dist, it.z + Math.cos(it.rot) * dist];
  }
  wallSides(): Side[] {
    const s: Side[] = ['n', 's', 'e', 'w'];
    return s.sort(() => this.r() - 0.5);
  }
  windowsOn(): Opening[] { return this.room.openings.filter((o) => o.kind === 'window' || o.kind === 'stairwindow'); }
  /** Sides sorted with walls that have no windows or doors first: good for big furniture. */
  quietSides(): Side[] {
    const score = (s: Side) => this.room.openings.filter((o) => o.side === s).reduce((t, o) => t + (o.t1 - o.t0), 0) - (this.sideRange(s)[1] - this.sideRange(s)[0]) * 0.3;
    return (['n', 's', 'e', 'w'] as Side[]).sort((a, b) => score(a) - score(b));
  }
  opposite(s: Side): Side { return s === 'n' ? 's' : s === 's' ? 'n' : s === 'e' ? 'w' : 'e'; }
}

// ---------------------------------------------------------------- per room type
function living(F: RoomFurnisher) {
  const q = F.quietSides();
  const unit = F.wall('wallunit', q.slice(0, 2), 'center');
  const sofaSide = q.find((s) => !unit || sideOf(F, unit) !== s) || q[1];
  const sofa = F.wall('sofa', [sofaSide, ...q], 'center');
  if (sofa) {
    F.add('wallcarpet', sofa.x - Math.sin(sofa.rot) * 0.4, F.room.y + 0.95, sofa.z - Math.cos(sofa.rot) * 0.4, sofa.rot, null);
    const [cx, cz] = F.inFront(sofa, 1.05);
    const ct = F.at('coffeetable', cx, cz, sofa.rot);
    if (ct) {
      for (const s of [1, -1]) {
        const ax = cx + Math.cos(sofa.rot) * s * 1.05 + Math.sin(sofa.rot) * 0.15, az = cz - Math.sin(sofa.rot) * s * 1.05 + Math.cos(sofa.rot) * 0.15;
        F.at('armchair', ax, az, Math.atan2(-s * Math.cos(sofa.rot), s * Math.sin(sofa.rot)));
      }
    }
    // the television faces the sofa
    const tvSide = F.opposite(sideOf(F, sofa));
    const tv = F.wall('tv', [tvSide], 'center', { gap: 0.08 }) || F.wall('tv', q, 'corner', { gap: 0.08 });
    void tv;
  } else F.wall('tv', q, 'corner');
  if (unit) F.add('radio', unit.x + Math.cos(unit.rot) * 0.7 + Math.sin(unit.rot) * 0.05, F.room.y + 1.02, unit.z - Math.sin(unit.rot) * 0.7 + Math.cos(unit.rot) * 0.05, unit.rot, null);
  else F.wall('radio', q, 'any', { y: 0 });
  const rugAt = sofa ? F.inFront(sofa, 1.05) : [(F.room.rect.x0 + F.room.rect.x1) / 2, (F.room.rect.z0 + F.room.rect.z1) / 2];
  F.add('rug', rugAt[0], F.room.y + 0.003, rugAt[1], sofa ? sofa.rot : 0, null);
  if (F.W * F.D > 16 && chance(F.r, 0.6)) {
    const t = F.at('diningtable', F.room.rect.x0 + 1.1, F.room.rect.z1 - 1.0, 0) || F.at('diningtable', F.room.rect.x1 - 1.1, F.room.rect.z0 + 1.0, 0);
    if (t) for (const [dx, dz, rot] of [[0, -0.6, 0], [0, 0.6, Math.PI], [-0.75, 0, Math.PI / 2], [0.75, 0, -Math.PI / 2]] as const) F.at('chair', t.x + dx, t.z + dz, rot);
  }
  for (const w of F.windowsOn().slice(0, 1)) if (chance(F.r, 0.7)) plantBy(F, w);
  if (chance(F.r, 0.3)) F.wall('sewingmachine', q.slice(2), 'corner');
  F.wall('picture', q, 'any');
}
function bedroom(F: RoomFurnisher, kids: boolean) {
  const q = F.quietSides();
  const bed = kids ? F.wall('bed1', q, 'corner') : F.wall('bed2', q, 'center');
  if (bed) {
    F.add('wallcarpet', bed.x - Math.sin(bed.rot) * 0.02, F.room.y + 0.9, bed.z - Math.cos(bed.rot) * 0.02, bed.rot, null);
    if (!kids) for (const s of [1, -1]) {
      const nx = bed.x + Math.cos(bed.rot) * s * 1.05 - Math.sin(bed.rot) * 0.78, nz = bed.z - Math.sin(bed.rot) * s * 1.05 - Math.cos(bed.rot) * 0.78;
      F.at('nightstand', nx, nz, bed.rot);
    }
    const [rx, rz] = F.inFront(bed, 1.25);
    F.add('rug', rx, F.room.y + 0.003, rz, bed.rot + Math.PI / 2, null);
  }
  F.wall('wardrobe', q, 'corner');
  if (kids) { const d = F.wall('desk', F.wallSides(), 'any'); if (d) { const [x, z] = F.inFront(d, 0.45); F.at('chair', x, z, d.rot + Math.PI); } F.wall('bed1', q, 'corner'); }
  else F.wall('dresser', F.wallSides(), 'any');
  if (chance(F.r, 0.25)) F.wall('ironingboard', F.wallSides(), 'any');
}
function kitchen(F: RoomFurnisher) {
  // the counter runs along the window wall if there is one: sink under the window, the aragaz beside it
  const win = F.windowsOn()[0];
  const sides: Side[] = win ? [win.side, ...F.quietSides()] : F.quietSides();
  let placed = false;
  for (const side of sides) {
    const spans = F.spans(side, { w: 1.9, d: 0.6, h: 0.88 });
    if (!spans.length) continue;
    const [a, b] = spans.sort((p, q2) => (q2[1] - q2[0]) - (p[1] - p[0]))[0];
    let t = a + 0.05;
    for (const type of ['cupboard', 'sink', 'stove', 'cupboard']) {
      const def = FURNITURE[type];
      if (t + def.w > b - 0.02) break;
      const pose = F.wallPose(side, t + def.w / 2, def);
      if (F.free(pose.fp)) F.add(type, pose.x, F.room.y, pose.z, pose.rot, pose.fp, type === 'stove' ? { on: chance(F.r, 0.3) } : {});
      t += def.w;
    }
    const sh = F.wallPose(side, (a + Math.min(b, a + 1.6)) / 2, FURNITURE.shelf);
    if (!win || side !== win.side) F.add('shelf', sh.x, F.room.y + 1.55, sh.z, sh.rot, null);
    placed = true;
    break;
  }
  void placed;
  F.wall('fridge', F.quietSides(), 'corner');
  const R = F.room.rect;
  const tx = (R.x0 + R.x1) / 2, tz = (R.z0 + R.z1) / 2;
  const t = F.at('kitchentable', tx, tz, 0) || F.wall('kitchentable', F.quietSides(), 'any');
  if (t) for (const [dx, dz] of [[-0.42, 0.45], [0.42, 0.45], [0, -0.5]] as const) F.at('stool', t.x + dx * Math.cos(t.rot) + dz * Math.sin(t.rot), t.z - dx * Math.sin(t.rot) + dz * Math.cos(t.rot), 0);
  F.wall('speaker', F.quietSides(), 'any');
  F.wall('calendar', F.wallSides(), 'any');
}
function bath(F: RoomFurnisher) {
  const W = F.W, D = F.D;
  const short: Side[] = W < D ? ['n', 's'] : ['w', 'e'];
  if (Math.min(W, D) >= 1.5) F.wall('tub', short, 'center') || F.wall('tub', ['n', 's', 'e', 'w'], 'any');
  const b = F.wall('basin', F.quietSides(), 'any');
  if (b) F.add('mirror', b.x - Math.sin(b.rot) * 0.2, F.room.y + 1.25, b.z - Math.cos(b.rot) * 0.2, b.rot, null);
  F.wall('toilet', F.quietSides(), 'corner');
}
function hall(F: RoomFurnisher) {
  F.wall('coatrack', F.quietSides(), 'corner');
  F.wall('shoecabinet', F.quietSides(), 'any');
  if (chance(F.r, 0.4)) F.wall('phonetable', F.quietSides(), 'any');
  F.wall('mirror', F.quietSides(), 'any');
}
function lobby(F: RoomFurnisher) {
  F.wall('mailboxes', ['e', 'w'], 'any');
  F.wall('radiator', ['e', 'w'], 'any');
}
function storage(F: RoomFurnisher) {
  F.wall('shelves', F.quietSides(), 'any');
  F.wall('shelves', F.quietSides(), 'any');
  for (let i = 0; i < 3; i++) F.wall('crate', F.wallSides(), 'any');
}
function shop(F: RoomFurnisher) {
  const front = F.room.openings.find((o) => o.kind === 'shopfront' || o.kind === 'entrance');
  const back: Side = front ? F.opposite(front.side) : 'n';
  F.wall('shopshelf', [back], 'center'); F.wall('shopshelf', [back], 'any');
  const R = F.room.rect;
  // counter parallel to the back wall, two metres out
  const def = FURNITURE.shopcounter;
  const off = 1.25 + def.d / 2;
  const [cx, cz] = back === 'n' ? [(R.x0 + R.x1) / 2, R.z0 + off] : back === 's' ? [(R.x0 + R.x1) / 2, R.z1 - off] : back === 'w' ? [R.x0 + off, (R.z0 + R.z1) / 2] : [R.x1 - off, (R.z0 + R.z1) / 2];
  const rot = back === 'n' ? Math.PI : back === 's' ? 0 : back === 'w' ? -Math.PI / 2 : Math.PI / 2;
  const c = F.at('shopcounter', cx, cz, rot);
  if (c) F.add('scale', c.x + Math.cos(c.rot) * 0.6, F.room.y + def.h, c.z - Math.sin(c.rot) * 0.6, c.rot, null);
  for (const s of (['e', 'w', 'n', 's'] as Side[]).filter((x) => x !== back && x !== front?.side)) F.wall('shopshelf', [s], 'any');
  for (let i = 0; i < 4; i++) F.wall('crate', F.wallSides(), 'any');
  F.wall('portraitshadow', [back], 'center');
}
function classroom(F: RoomFurnisher) {
  const board = (F.D > F.W ? 'n' : 'w') as Side;
  F.wall('blackboard', [board, F.opposite(board)], 'center');
  F.wall('portraitshadow', [board], 'center');
  const R = F.room.rect;
  const rot = board === 'n' ? Math.PI : board === 's' ? 0 : board === 'w' ? -Math.PI / 2 : Math.PI / 2;
  const along = board === 'n' || board === 's';
  const u0 = along ? R.x0 : R.z0, u1 = along ? R.x1 : R.z1;
  const v0 = board === 'n' ? R.z0 : board === 'w' ? R.x0 : board === 's' ? R.z1 : R.x1;
  const dirV = board === 'n' || board === 'w' ? 1 : -1;
  const vSpan = along ? R.z1 - R.z0 : R.x1 - R.x0;
  const teacher = along ? F.at('teacherdesk', (u0 + u1) / 2 + 1.5, v0 + dirV * 1.3, rot) : F.at('teacherdesk', v0 + dirV * 1.3, (u0 + u1) / 2 + 1.5, rot);
  void teacher;
  for (let v = 2.6; v < vSpan - 0.8; v += 1.15) for (let u = u0 + 1.0; u < u1 - 0.9; u += 1.6) {
    const vv = v0 + dirV * v;
    if (along) F.at('schooldesk', u + 0.55, vv, rot + Math.PI); else F.at('schooldesk', vv, u + 0.55, rot + Math.PI);
  }
}
function office(F: RoomFurnisher) {
  F.wall('portraitshadow', F.quietSides(), 'center');
  for (let i = 0; i < 3; i++) { const d = F.wall('desk', F.wallSides(), 'any'); if (d) { const [x, z] = F.inFront(d, 0.45); F.at('chair', x, z, d.rot + Math.PI); } }
  F.wall('filing', F.quietSides(), 'corner'); F.wall('filing', F.quietSides(), 'corner');
  F.wall('calendar', F.wallSides(), 'any');
}
function workshop(F: RoomFurnisher) {
  const R = F.room.rect;
  for (let x = R.x0 + 2.5; x < R.x1 - 2; x += 3.4) for (let z = R.z0 + 2.4; z < R.z1 - 2; z += 3.0) if (chance(F.r, 0.75)) F.at('lathe', x, z, chance(F.r, 0.5) ? 0 : Math.PI);
  for (let i = 0; i < 4; i++) F.wall('workbench', F.wallSides(), 'any');
  for (let i = 0; i < 5; i++) F.wall('barrel', F.wallSides(), 'corner');
  F.wall('portraitshadow', F.quietSides(), 'center');
}
function nave(F: RoomFurnisher) {
  const entr = F.room.openings.find((o) => o.kind === 'entrance');
  const east: Side = entr ? F.opposite(entr.side) : 'e';
  F.wall('iconostasis', [east], 'center');
  const R = F.room.rect;
  for (let i = 0; i < 3; i++) F.at('candlestand', R.x0 + (R.x1 - R.x0) * (0.3 + 0.2 * i), (R.z0 + R.z1) / 2, 0);
  for (const s of (['n', 's', 'e', 'w'] as Side[]).filter((x) => x !== east && x !== entr?.side)) { F.wall('bench', [s], 'any'); F.wall('bench', [s], 'any'); }
}
function garage(F: RoomFurnisher) {
  if (chance(F.r, 0.6)) {
    const R = F.room.rect;
    const along = F.D > F.W;
    F.at('car', (R.x0 + R.x1) / 2, (R.z0 + R.z1) / 2, along ? 0 : Math.PI / 2);
  }
  F.wall('shelves', F.quietSides(), 'any');
  F.wall('tyres', F.quietSides(), 'corner');
  F.wall('crate', F.wallSides(), 'any');
}
function porch(F: RoomFurnisher) {
  F.wall('bench', F.quietSides(), 'any');
  for (const w of F.windowsOn().slice(0, 2)) plantBy(F, w);
  F.wall('crate', F.wallSides(), 'any');
}
function stair(F: RoomFurnisher) { void F; }

function plantBy(F: RoomFurnisher, w: Opening) {
  const def = FURNITURE.plant;
  const t = w.t1 + 0.3;
  const pose = F.wallPose(w.side, t, def, 0.05);
  if (F.free(pose.fp)) F.add('plant', pose.x, F.room.y, pose.z, pose.rot, pose.fp);
}
function sideOf(F: RoomFurnisher, it: FurnitureItem): Side {
  const R = F.room.rect;
  const d = [['n', Math.abs(it.z - R.z0)], ['s', Math.abs(it.z - R.z1)], ['w', Math.abs(it.x - R.x0)], ['e', Math.abs(it.x - R.x1)]] as [Side, number][];
  return d.sort((a, b) => a[1] - b[1])[0][0];
}

/** Window furnishings and fittings every room gets: radiators under windows, curtains, a light. */
function fittings(F: RoomFurnisher) {
  const room = F.room;
  const R = room.rect;
  const homely = ['living', 'bedroom', 'kids', 'kitchen', 'office', 'classroom', 'hall', 'shop', 'porch'].includes(room.type);
  for (const o of room.openings) {
    if (!(o.kind === 'window' || o.kind === 'stairwindow') || !o.exterior) continue;
    const c = (o.t0 + o.t1) / 2, w = o.t1 - o.t0;
    const pose = F.wallPose(o.side, c, FURNITURE.radiator, 0.06);
    if (o.y0 > 0.7 && homely) F.add('radiator', pose.x, room.y + 0.14, pose.z, pose.rot, null, { variant: Math.min(3, Math.round(w)) });
    if (['living', 'bedroom', 'kids', 'kitchen', 'office'].includes(room.type)) {
      const cp = F.wallPose(o.side, c, FURNITURE.curtain, 0.12);
      F.add('curtain', cp.x, room.y + Math.max(0.0, o.y0 - 0.15), cp.z, cp.rot, null, { variant: Math.floor(F.r() * 4) });
      const it = room.furniture[room.furniture.length - 1];
      it.w = +(w + 0.35).toFixed(2);
      it.h = +(Math.min(room.h - 0.1, o.y1 + 0.25) - Math.max(0, o.y0 - 0.15)).toFixed(2);
    }
  }
  if (room.type !== 'stair' && room.type !== 'lobby') F.add(room.type === 'bath' || room.type === 'storage' || room.type === 'hall' || room.type === 'garage' ? 'bulb' : 'lamp', (R.x0 + R.x1) / 2, room.y + room.h - 0.02, (R.z0 + R.z1) / 2, 0, null, { variant: Math.floor(F.r() * 3) });
  else F.add('bulb', (R.x0 + R.x1) / 2, room.y + room.h - 0.02, (R.z0 + R.z1) / 2, 0, null);
}

export function furnishPlan(plan: BuildingPlan): void {
  for (const room of plan.rooms) {
    const F = new RoomFurnisher(room);
    switch (room.type) {
      case 'living': living(F); break;
      case 'bedroom': bedroom(F, false); break;
      case 'kids': bedroom(F, true); break;
      case 'kitchen': kitchen(F); break;
      case 'bath': bath(F); break;
      case 'hall': hall(F); break;
      case 'lobby': lobby(F); break;
      case 'stair': stair(F); break;
      case 'storage': storage(F); break;
      case 'shop': shop(F); break;
      case 'classroom': classroom(F); break;
      case 'office': office(F); break;
      case 'workshop': workshop(F); break;
      case 'nave': nave(F); break;
      case 'garage': garage(F); break;
      case 'porch': porch(F); break;
      default: break;
    }
    fittings(F);
    void pick;
  }
}
