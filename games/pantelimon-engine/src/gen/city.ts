// ===================================================================
// The city: spatial indexes over the OSM-derived data, the streaming tile
// grid, and street furniture generated per tile (trees, lamps, parked
// cars, benches, bins). Deterministic and engine-independent.
// ===================================================================
import type { CityData, CityRoad, PropPlacement, V2 } from '../data/schema';
import { centroid, distToSegment, pointInPoly } from '../core/geom';
import { rngFor, chance, pick } from '../core/rng';
import type { PlanContext, RoadHit } from './plan';

export const TILE = 96;

interface Seg { ax: number; az: number; bx: number; bz: number; road: number }

export class City implements PlanContext {
  segGrid = new Map<string, Seg[]>();
  bldGrid = new Map<string, number[]>();
  tiles = new Map<string, { buildings: number[]; roads: number[]; areas: number[] }>();
  readonly cell = 24;
  constructor(public data: CityData) {
    data.roads.forEach((r, ri) => {
      for (let i = 0; i < r.pts.length - 1; i++) {
        const [ax, az] = r.pts[i], [bx, bz] = r.pts[i + 1];
        const s: Seg = { ax, az, bx, bz, road: ri };
        const pad = r.width / 2 + 2;
        for (const k of this.cellsOver(Math.min(ax, bx) - pad, Math.min(az, bz) - pad, Math.max(ax, bx) + pad, Math.max(az, bz) + pad, this.cell)) {
          let l = this.segGrid.get(k); if (!l) this.segGrid.set(k, (l = [])); l.push(s);
        }
        for (const k of this.cellsOver(Math.min(ax, bx) - pad, Math.min(az, bz) - pad, Math.max(ax, bx) + pad, Math.max(az, bz) + pad, TILE)) this.tile(k).roads.push(ri);
      }
    });
    data.buildings.forEach((b, bi) => {
      let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
      for (const [x, z] of b.poly) { x0 = Math.min(x0, x); z0 = Math.min(z0, z); x1 = Math.max(x1, x); z1 = Math.max(z1, z); }
      for (const k of this.cellsOver(x0, z0, x1, z1, this.cell)) { let l = this.bldGrid.get(k); if (!l) this.bldGrid.set(k, (l = [])); l.push(bi); }
      const [cx, cz] = centroid(b.poly);
      this.tile(this.tileKey(cx, cz)).buildings.push(bi);
    });
    data.areas.forEach((a, ai) => {
      let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
      for (const [x, z] of a.poly) { x0 = Math.min(x0, x); z0 = Math.min(z0, z); x1 = Math.max(x1, x); z1 = Math.max(z1, z); }
      for (const k of this.cellsOver(x0, z0, x1, z1, TILE)) this.tile(k).areas.push(ai);
    });
    for (const t of this.tiles.values()) t.roads = [...new Set(t.roads)];
  }
  private tile(k: string) { let t = this.tiles.get(k); if (!t) this.tiles.set(k, (t = { buildings: [], roads: [], areas: [] })); return t; }
  tileKey(x: number, z: number): string { return `${Math.floor(x / TILE)},${Math.floor(z / TILE)}`; }
  private *cellsOver(x0: number, z0: number, x1: number, z1: number, size: number) {
    for (let i = Math.floor(x0 / size); i <= Math.floor(x1 / size); i++) for (let j = Math.floor(z0 / size); j <= Math.floor(z1 / size); j++) yield `${i},${j}`;
  }
  roadNear(x: number, z: number, maxDist = 80): RoadHit | null {
    let best: RoadHit | null = null;
    const R = Math.ceil(maxDist / this.cell);
    const ci = Math.floor(x / this.cell), cj = Math.floor(z / this.cell);
    const seen = new Set<Seg>();
    for (let i = ci - R; i <= ci + R; i++) for (let j = cj - R; j <= cj + R; j++) {
      for (const s of this.segGrid.get(`${i},${j}`) || []) {
        if (seen.has(s)) continue; seen.add(s);
        const road = this.data.roads[s.road];
        if (road.kind === 'path' || road.kind === 'service') continue;
        const d = distToSegment(x, z, s.ax, s.az, s.bx, s.bz);
        // prefer big roads a little: they decide where shops face
        const score = d - (road.kind === 'primary' ? 14 : road.kind === 'secondary' ? 8 : 0);
        if (!best || score < (best as RoadHit & { score: number }).score) {
          const dx = s.bx - s.ax, dz = s.bz - s.az, l2 = dx * dx + dz * dz;
          const t = l2 > 0 ? Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / l2)) : 0;
          const px = s.ax + dx * t - x, pz = s.az + dz * t - z, pl = Math.hypot(px, pz) || 1;
          best = { dist: d, dx: px / pl, dz: pz / pl, kind: road.kind, name: road.name, score } as RoadHit & { score: number };
        }
      }
    }
    return best;
  }
  /** Is a point on a carriageway? (paths don't count) */
  onRoad(x: number, z: number, pad = 0): CityRoad | null {
    for (const s of this.segGrid.get(`${Math.floor(x / this.cell)},${Math.floor(z / this.cell)}`) || []) {
      const road = this.data.roads[s.road];
      if (road.kind === 'path') continue;
      if (distToSegment(x, z, s.ax, s.az, s.bx, s.bz) < road.width / 2 + pad) return road;
    }
    return null;
  }
  inBuilding(x: number, z: number, pad = 0): boolean {
    for (const bi of this.bldGrid.get(`${Math.floor(x / this.cell)},${Math.floor(z / this.cell)}`) || []) {
      const b = this.data.buildings[bi];
      if (pointInPoly(x, z, b.poly)) return true;
      if (pad > 0) for (let i = 0; i < b.poly.length; i++) {
        const [ax, az] = b.poly[i], [bx, bz] = b.poly[(i + 1) % b.poly.length];
        if (distToSegment(x, z, ax, az, bx, bz) < pad) return true;
      }
    }
    return false;
  }
  streetName(x: number, z: number): string {
    const h = this.roadNear(x, z, 40);
    return h && h.dist < 30 ? h.name : '';
  }

  /** Street furniture for one tile, the same every time. */
  props(key: string): PropPlacement[] {
    const t = this.tiles.get(key);
    const out: PropPlacement[] = [];
    if (!t) return out;
    const [ti, tj] = key.split(',').map(Number);
    const inTile = (x: number, z: number) => Math.floor(x / TILE) === ti && Math.floor(z / TILE) === tj;
    const free = (x: number, z: number, r: number) => !this.inBuilding(x, z, r) && !this.onRoad(x, z, 0.4);
    for (const ri of t.roads) {
      const road = this.data.roads[ri];
      if (road.kind === 'path' || road.kind === 'service') continue;
      const rr = rngFor('props', road.id, key);
      const big = road.kind === 'primary' || road.kind === 'secondary';
      for (let i = 0; i < road.pts.length - 1; i++) {
        const [ax, az] = road.pts[i], [bx, bz] = road.pts[i + 1];
        const len = Math.hypot(bx - ax, bz - az);
        if (len < 1) continue;
        const ux = (bx - ax) / len, uz = (bz - az) / len, nx = -uz, nz = ux;
        const ang = Math.atan2(ux, uz);
        // trees on the verges
        const step = big ? 9 : 11;
        for (let d = (rr() * step) | 0; d < len; d += step + rr() * 3) {
          for (const side of [1, -1]) {
            const off = road.width / 2 + (big ? 4.2 : 2.6) + rr() * 0.6;
            const x = ax + ux * d + nx * off * side, z = az + uz * d + nz * off * side;
            if (!inTile(x, z) || !chance(rr, big ? 0.85 : 0.55) || !free(x, z, 2.2)) continue;
            out.push({ type: 'tree', x, z, y: 0.1, rot: rr() * Math.PI * 2, variant: big ? (chance(rr, 0.6) ? 0 : 1) : chance(rr, 0.5) ? 0 : 3, scale: 0.85 + rr() * 0.3 });
          }
        }
        // concrete lamp posts with rectangular holes
        const lstep = big ? 34 : 30;
        for (let d = 10 + ((rr() * 8) | 0); d < len; d += lstep) {
          const side = big ? (Math.floor(d / lstep) % 2 ? 1 : -1) : 1;
          const off = road.width / 2 + 0.8;
          const x = ax + ux * d + nx * off * side, z = az + uz * d + nz * off * side;
          if (!inTile(x, z) || !free(x, z, 0.6)) continue;
          out.push({ type: 'lamppost', x, z, y: 0.15, rot: Math.atan2(-nx * side, -nz * side), variant: chance(rr, 0.2) ? 1 : 0 });
        }
        // Dacias parked along the kerb of side streets, some up on bricks
        if (!big && road.surface !== 'dirt') {
          for (let d = 4 + rr() * 6; d < len - 3; d += 6 + rr() * 14) {
            if (!chance(rr, 0.35)) continue;
            const side = chance(rr, 0.5) ? 1 : -1;
            const off = road.width / 2 - 1.0;
            const x = ax + ux * d + nx * off * side, z = az + uz * d + nz * off * side;
            if (!inTile(x, z) || this.inBuilding(x, z, 1.5)) continue;
            out.push({ type: 'car', x, z, y: 0, rot: ang + (side > 0 ? Math.PI : 0) - Math.PI / 2, variant: Math.floor(rr() * 9) });
          }
        }
      }
    }
    // trees and benches in courtyards (open ground between the blocks)
    const rc = rngFor('court', key);
    for (let k = 0; k < 22; k++) {
      const x = (ti + rc()) * TILE, z = (tj + rc()) * TILE;
      if (!free(x, z, 3.5)) continue;
      const near = this.roadNear(x, z, 30);
      if (near && near.dist < 6) continue;
      out.push({ type: 'tree', x, z, y: 0.1, rot: rc() * Math.PI * 2, variant: pick(rc, [0, 1, 2, 2, 3]), scale: 0.8 + rc() * 0.45 });
    }
    for (let k = 0; k < 4; k++) {
      const x = (ti + rc()) * TILE, z = (tj + rc()) * TILE;
      if (!free(x, z, 1.5)) continue;
      out.push({ type: chance(rc, 0.5) ? 'bench' : 'bin', x, z, y: 0.12, rot: rc() * Math.PI * 2, variant: 0 });
    }
    for (const [x, z] of this.data.trees) if (inTile(x, z)) out.push({ type: 'tree', x, z, y: 0.1, rot: rc() * 6.28, variant: 1, scale: 1 });
    return out;
  }
}
export type { V2 };
