// ===================================================================
// Player collision: a vertical capsule against building walls (from the
// plans of nearby buildings, or the bare footprint while a plan is still
// loading), props and parked cars; standing height from floors, landings,
// stair flights, entrance steps and the pavement raster.
// No three.js: runs headless in tests.
// ===================================================================
import type { BuildingPlan, CityData, V2 } from '../data/schema';
import { collisionFromPlan, slopeY, type PlanCollision, type Seg } from './walls';
import { TILE } from '../gen/city';
import { HRES } from '../mesh/ground';

interface BCol { bi: number; cx: number; cz: number; c: number; s: number; col: PlanCollision; r: number }
interface Circle { x: number; z: number; r: number }
interface OBox { cx: number; cz: number; hx: number; hz: number; c: number; s: number }

export const STEP = 0.5;      // the highest step you walk up without jumping
export const RADIUS = 0.26;

export class Collider {
  plans = new Map<number, BCol>();
  heights = new Map<string, { h: Float32Array; n: number; x0: number; z0: number }>();
  circles = new Map<string, Circle[]>();
  boxes = new Map<string, OBox[]>();
  private footprints = new Map<number, Seg[]>();
  /** Moving obstacles in world coordinates (door leaves), refreshed every frame. */
  dynamic: Seg[] = [];
  constructor(private data: CityData) {}

  addPlan(bi: number, plan: BuildingPlan) {
    const col = collisionFromPlan(plan);
    let r = 0;
    for (const w of plan.wings) r = Math.max(r, Math.hypot(w.x0, w.z0), Math.hypot(w.x1, w.z1), Math.hypot(w.x0, w.z1), Math.hypot(w.x1, w.z0));
    this.plans.set(bi, { bi, cx: plan.frame.cx, cz: plan.frame.cz, c: Math.cos(plan.frame.angle), s: Math.sin(plan.frame.angle), col, r: r + 6 });
  }
  removePlan(bi: number) { this.plans.delete(bi); }
  addTile(key: string, h: Float32Array, n: number, x0: number, z0: number, circles: Circle[], boxes: OBox[]) {
    this.heights.set(key, { h, n, x0, z0 }); this.circles.set(key, circles); this.boxes.set(key, boxes);
  }
  removeTile(key: string) { this.heights.delete(key); this.circles.delete(key); this.boxes.delete(key); }
  private footprint(bi: number): Seg[] {
    let f = this.footprints.get(bi);
    if (!f) {
      const p: V2[] = this.data.buildings[bi].poly;
      f = p.map((a, i) => { const b = p[(i + 1) % p.length]; return { ax: a[0], az: a[1], bx: b[0], bz: b[1], y0: -5, y1: 200 }; });
      this.footprints.set(bi, f);
    }
    return f;
  }
  /** Buildings whose footprint is within `d` of a point (by bounding radius). */
  nearBuildings(x: number, z: number, d: number, out: number[] = []): number[] {
    out.length = 0;
    const bs = this.data.buildings;
    for (let i = 0; i < bs.length; i++) {
      const b = bs[i] as unknown as { _c?: [number, number, number] };
      let c = b._c;
      if (!c) {
        const poly = bs[i].poly;
        let cx = 0, cz = 0; for (const q of poly) { cx += q[0]; cz += q[1]; } cx /= poly.length; cz /= poly.length;
        let r = 0; for (const q of poly) r = Math.max(r, Math.hypot(q[0] - cx, q[1] - cz));
        c = b._c = [cx, cz, r];
      }
      if (Math.hypot(x - c[0], z - c[1]) < c[2] + d) out.push(i);
    }
    return out;
  }

  /** Standing height under (x, z) for feet at `feetY`. */
  groundAt(x: number, z: number, feetY: number): number {
    let best = this.pavement(x, z);
    const lim = feetY + STEP;
    for (const b of this.plans.values()) {
      const dx = x - b.cx, dz = z - b.cz;
      if (dx * dx + dz * dz > b.r * b.r) continue;
      const lx = dx * b.c - dz * b.s, lz = dx * b.s + dz * b.c;
      for (const r of b.col.rects) if (lx >= r.x0 && lx <= r.x1 && lz >= r.z0 && lz <= r.z1 && r.y <= lim && r.y > best) best = r.y;
      for (const s of b.col.slopes) if (lx >= s.x0 && lx <= s.x1 && lz >= s.z0 && lz <= s.z1) { const y = slopeY(s, lx, lz); if (y <= lim && y > best) best = y; }
    }
    return best;
  }
  pavement(x: number, z: number): number {
    const t = this.heights.get(`${Math.floor(x / TILE)},${Math.floor(z / TILE)}`);
    if (!t) return 0;
    const i = Math.floor((x - t.x0) / HRES), j = Math.floor((z - t.z0) / HRES);
    return i >= 0 && j >= 0 && i < t.n && j < t.n ? t.h[j * t.n + i] : 0;
  }

  /** Push a capsule at (x, z) with feet at feetY out of everything it overlaps. */
  resolve(p: { x: number; z: number }, feetY: number, r = RADIUS) {
    const ya = feetY + 0.35, yb = feetY + 1.7;
    for (let it = 0; it < 3; it++) {
      for (const b of this.plans.values()) {
        const dx = p.x - b.cx, dz = p.z - b.cz;
        if (dx * dx + dz * dz > b.r * b.r) continue;
        const l = { x: dx * b.c - dz * b.s, z: dx * b.s + dz * b.c };
        let moved = false;
        for (const s of b.col.segs) if (s.y1 > ya && s.y0 < yb && pushSeg(l, s, r)) moved = true;
        if (moved) { p.x = b.cx + l.x * b.c + l.z * b.s; p.z = b.cz - l.x * b.s + l.z * b.c; }
      }
      for (const s of this.dynamic) if (s.y1 > ya && s.y0 < yb) pushSeg(p, s, r);
      // buildings near enough to touch whose plan isn't loaded yet: solid footprints
      for (const bi of this.nearBuildings(p.x, p.z, 1.5, this.tmp)) if (!this.plans.has(bi)) for (const s of this.footprint(bi)) pushSeg(p, s, r);
      const key = `${Math.floor(p.x / TILE)},${Math.floor(p.z / TILE)}`;
      for (const c of this.circles.get(key) || []) {
        const dx = p.x - c.x, dz = p.z - c.z, d = Math.hypot(dx, dz), m = c.r + r;
        if (d < m && d > 1e-6) { p.x = c.x + (dx / d) * m; p.z = c.z + (dz / d) * m; }
      }
      if (feetY < 1.2) for (const bx of this.boxes.get(key) || []) pushBox(p, bx, r);
    }
  }
  private tmp: number[] = [];
}

function pushSeg(p: { x: number; z: number }, s: Seg, r: number): boolean {
  const ex = s.bx - s.ax, ez = s.bz - s.az, l2 = ex * ex + ez * ez;
  const t = l2 > 0 ? Math.max(0, Math.min(1, ((p.x - s.ax) * ex + (p.z - s.az) * ez) / l2)) : 0;
  const qx = s.ax + ex * t, qz = s.az + ez * t;
  const dx = p.x - qx, dz = p.z - qz, d = Math.hypot(dx, dz);
  if (d >= r) return false;
  if (d < 1e-6) { const nl = Math.sqrt(l2) || 1; p.x = qx - (ez / nl) * r; p.z = qz + (ex / nl) * r; return true; }
  p.x = qx + (dx / d) * r; p.z = qz + (dz / d) * r;
  return true;
}
function pushBox(p: { x: number; z: number }, b: OBox, r: number) {
  const dx = p.x - b.cx, dz = p.z - b.cz;
  const lx = dx * b.c - dz * b.s, lz = dx * b.s + dz * b.c;
  const qx = Math.max(-b.hx, Math.min(b.hx, lx)), qz = Math.max(-b.hz, Math.min(b.hz, lz));
  let ox = lx - qx, oz = lz - qz;
  let d = Math.hypot(ox, oz);
  if (d >= r) return;
  if (d < 1e-6) { // inside: leave by the nearest face
    const px = b.hx - Math.abs(lx), pz = b.hz - Math.abs(lz);
    if (px < pz) { ox = Math.sign(lx) || 1; oz = 0; } else { ox = 0; oz = Math.sign(lz) || 1; }
    d = 0;
    const nx = (Math.abs(ox) > 0 ? Math.sign(ox) * b.hx : qx) + ox * r, nz = (Math.abs(oz) > 0 ? Math.sign(oz) * b.hz : qz) + oz * r;
    p.x = b.cx + nx * b.c + nz * b.s; p.z = b.cz - nx * b.s + nz * b.c;
    return;
  }
  const nx = qx + (ox / d) * r, nz = qz + (oz / d) * r;
  p.x = b.cx + nx * b.c + nz * b.s; p.z = b.cz - nx * b.s + nz * b.c;
}
