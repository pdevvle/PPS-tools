// ===================================================================
// Ground for one streaming tile: verges, parks and car parks, roads
// (asphalt, granite setts, dirt), raised pavements with kerbs, footpaths,
// tram rails and the catenary. Also a walk-height raster so the player
// steps up onto pavements.
// ===================================================================
import type { V2 } from '../data/schema';
import type { City } from '../gen/city';
import { TILE } from '../gen/city';
import { GeoBuilder, A, type Attr, type V3 } from './builder';
import { M } from './mat';
import { earcut } from '../core/earcut';
import { rngFor } from '../core/rng';

export const KERB = 0.15;
export const HRES = 0.5; // walk-height raster cell, metres
export interface TileGround { heights: Float32Array; n: number; x0: number; z0: number }

/** Build the tile's ground into `b` (world coordinates) and return its walk-height raster. */
export function buildGround(city: City, key: string, b: GeoBuilder): TileGround {
  const [ti, tj] = key.split(',').map(Number);
  const X0 = ti * TILE, Z0 = tj * TILE, X1 = X0 + TILE, Z1 = Z0 + TILE;
  const n = Math.round(TILE / HRES);
  const heights = new Float32Array(n * n);
  const t = city.tiles.get(key);
  const r = rngFor('ground', key);
  const inTile = (x: number, z: number) => x >= X0 && x < X1 && z >= Z0 && z < Z1;
  // verge: the whole tile, a little below everything else
  b.flat(X0, Z0, X1, Z1, 0, A('#3a3426', M.VERGE, { seed: r() }));
  if (!t) return { heights, n, x0: X0, z0: Z0 };
  const raise = (x: number, z: number, h: number) => {
    const i = Math.floor((x - X0) / HRES), j = Math.floor((z - Z0) / HRES);
    if (i >= 0 && j >= 0 && i < n && j < n) heights[j * n + i] = Math.max(heights[j * n + i], h);
  };

  // ---------------- areas (drawn by the tile holding their centroid)
  for (const ai of t.areas) {
    const a = city.data.areas[ai];
    const cx = a.poly.reduce((s, p) => s + p[0], 0) / a.poly.length, cz = a.poly.reduce((s, p) => s + p[1], 0) / a.poly.length;
    if (!inTile(cx, cz)) continue;
    const att = a.kind === 'parking' ? A('#3a3a3a', M.ASPHALT, { seed: r(), aux: [0, 0] }) : a.kind === 'pitch' ? A('#5a5040', M.GRAVEL, { seed: r() }) : a.kind === 'playground' ? A('#6a5a44', M.GRAVEL, { seed: r() }) : A('#3a3a28', M.VERGE, { seed: r() });
    const y = a.kind === 'grass' ? 0.03 : 0.025;
    polyFill(b, a.poly, y, att);
  }

  // ---------------- roads, pavements, paths
  for (const ri of t.roads) {
    const road = city.data.roads[ri];
    const pts = road.pts;
    const isPath = road.kind === 'path';
    const big = road.kind === 'primary' || road.kind === 'secondary';
    const hw = road.width / 2;
    let dist = 0;
    for (let i = 0; i < pts.length - 1; i++) {
      const [ax, az] = pts[i], [bx, bz] = pts[i + 1];
      const len = Math.hypot(bx - ax, bz - az);
      if (len < 0.01) continue;
      const mx = (ax + bx) / 2, mz = (az + bz) / 2;
      const mine = inTile(mx, mz);
      const ux = (bx - ax) / len, uz = (bz - az) / len, nx = -uz, nz = ux;
      // mitre the ends against the neighbouring segments so ribbons join
      const mitre = (k: number): V2 => {
        const p = pts[k], prev = pts[k - 1], next = pts[k + 1];
        if (!prev || !next) return [nx, nz];
        const l0 = Math.hypot(p[0] - prev[0], p[1] - prev[1]) || 1, l1 = Math.hypot(next[0] - p[0], next[1] - p[1]) || 1;
        const n0: V2 = [-(p[1] - prev[1]) / l0, (p[0] - prev[0]) / l0], n1: V2 = [-(next[1] - p[1]) / l1, (next[0] - p[0]) / l1];
        let mx2 = n0[0] + n1[0], mz2 = n0[1] + n1[1];
        const ml = Math.hypot(mx2, mz2) || 1; mx2 /= ml; mz2 /= ml;
        const k2 = 1 / Math.max(0.35, mx2 * n0[0] + mz2 * n0[1]);
        return [mx2 * k2, mz2 * k2];
      };
      const ma = mitre(i), mb = mitre(i + 1);
      if (mine) {
        if (isPath) {
          ribbon(b, ax, az, bx, bz, ma, mb, -0.9, 0.9, 0.05, A('#4a4640', M.SIDEWALK, { seed: r() }), dist);
        } else {
          const surf: Attr = road.surface === 'cobble' ? A('#3a3836', M.COBBLE, { seed: r() }) : road.surface === 'dirt' ? A('#4a4034', M.GRAVEL, { seed: r() }) : A('#303030', M.ASPHALT, { seed: r(), aux: [hw, big ? 1 : 0] });
          ribbon(b, ax, az, bx, bz, ma, mb, -hw, hw, road.kind === 'service' ? 0.015 : 0.02, surf, dist);
        }
      }
      // pavements: 2 m pieces either side, skipped where they would cross another carriageway or a building
      if (!isPath && road.kind !== 'service') {
        const sw = big ? 3.4 : 2.2;
        const step = 2.0;
        for (let d = 0; d < len; d += step) {
          const d1 = Math.min(len, d + step);
          for (const side of [1, -1]) {
            const off = hw + sw / 2;
            const cx = ax + ux * (d + d1) / 2 + nx * off * side, cz = az + uz * (d + d1) / 2 + nz * off * side;
            if (!inTile(cx, cz)) continue;
            const other = city.onRoad(cx, cz, 0.2);
            if (other && other !== road) continue;
            if (city.inBuilding(cx, cz, 0)) continue;
            const p0x = ax + ux * d, p0z = az + uz * d, p1x = ax + ux * d1, p1z = az + uz * d1;
            const lo = side > 0 ? hw : -hw - sw, hi = side > 0 ? hw + sw : -hw;
            const sideA = A('#5a5650', M.SIDEWALK, { seed: r() });
            ribbon(b, p0x, p0z, p1x, p1z, [nx, nz], [nx, nz], lo, hi, KERB, sideA, dist + d);
            // kerb face toward the road
            const kx = side > 0 ? hw : -hw;
            const k0: V3 = [p0x + nx * kx, 0, p0z + nz * kx], k1: V3 = [p1x + nx * kx, 0, p1z + nz * kx];
            const face: V3 = [-nx * side, 0, -nz * side];
            kerbFace(b, k0, k1, face, A('#6e6a62', M.CONCRETE, { seed: r() }));
            for (let q = 0.25; q < 1; q += 0.5) for (let o = 0.25; o < sw; o += HRES) {
              const px = p0x + (p1x - p0x) * q + nx * (side > 0 ? hw + o : -hw - o), pz = p0z + (p1z - p0z) * q + nz * (side > 0 ? hw + o : -hw - o);
              raise(px, pz, KERB);
            }
          }
        }
      }
      dist += len;
    }
  }

  // ---------------- tram tracks and catenary
  for (const tr of city.data.trams) {
    let dist = 0;
    for (let i = 0; i < tr.pts.length - 1; i++) {
      const [ax, az] = tr.pts[i], [bx, bz] = tr.pts[i + 1];
      const len = Math.hypot(bx - ax, bz - az);
      if (len < 0.01) continue;
      const ux = (bx - ax) / len, uz = (bz - az) / len, nx = -uz, nz = ux;
      if (inTile((ax + bx) / 2, (az + bz) / 2)) {
        for (const off of [-0.7175, 0.7175]) {
          const rail = A('#3a3a38', M.RAIL, { seed: 0.3 });
          ribbon(b, ax, az, bx, bz, [nx, nz], [nx, nz], off - 0.035, off + 0.035, 0.05, rail, dist);
        }
      }
      // poles every 32 m, with the contact wire between
      for (let d = (32 - (dist % 32)) % 32; d < len; d += 32) {
        const px = ax + ux * d + nx * 2.6, pz = az + uz * d + nz * 2.6;
        if (!inTile(px, pz)) continue;
        const pole = A('#4a4c48', M.METAL, { seed: 0.4 });
        b.tube([px, 0, pz], [px, 7.2, pz], 0.11, 0.08, 6, pole, true);
        b.tube([px, 6.2, pz], [px - nx * 3.1, 6.2, pz - nz * 3.1], 0.03, 0.03, 4, pole, false);
        const wire = A('#2a2a2a', M.METAL);
        const cx = px - nx * 2.6, cz = pz - nz * 2.6, ex = cx + ux * 32, ez = cz + uz * 32;
        for (let k = 0; k < 8; k++) {
          const t0 = k / 8, t1 = (k + 1) / 8;
          const s0 = 6.0 - Math.sin(t0 * Math.PI) * 0.18, s1 = 6.0 - Math.sin(t1 * Math.PI) * 0.18;
          b.tube([cx + (ex - cx) * t0, s0, cz + (ez - cz) * t0], [cx + (ex - cx) * t1, s1, cz + (ez - cz) * t1], 0.007, 0.007, 3, wire, false);
        }
      }
      dist += len;
    }
  }
  return { heights, n, x0: X0, z0: Z0 };
}

function ribbon(b: GeoBuilder, ax: number, az: number, bx: number, bz: number, ma: V2, mb: V2, lo: number, hi: number, y: number, a: Attr, dist: number) {
  const len = Math.hypot(bx - ax, bz - az);
  const p0: V3 = [ax + ma[0] * lo, y, az + ma[1] * lo], p1: V3 = [bx + mb[0] * lo, y, bz + mb[1] * lo];
  const p2: V3 = [bx + mb[0] * hi, y, bz + mb[1] * hi], p3: V3 = [ax + ma[0] * hi, y, az + ma[1] * hi];
  // uv: x along the road in metres, y across (0 at the centre line)
  const uv: [number, number][] = [[dist, lo], [dist + len, lo], [dist + len, hi], [dist, hi]];
  const n = (p1[0] - p0[0]) * (p3[2] - p0[2]) - (p1[2] - p0[2]) * (p3[0] - p0[0]);
  if (n > 0) b.quad(p0, p3, p2, p1, a, [uv[0], uv[3], uv[2], uv[1]]); else b.quad(p0, p1, p2, p3, a, uv);
}
function kerbFace(b: GeoBuilder, k0: V3, k1: V3, face: V3, a: Attr) {
  const p = [k0, k1, [k1[0], KERB, k1[2]] as V3, [k0[0], KERB, k0[2]] as V3];
  const e1 = [p[1][0] - p[0][0], 0, p[1][2] - p[0][2]];
  // normal of (p0,p1,p3) is e1 × up
  const nx = -e1[2], nz = e1[0];
  if (nx * face[0] + nz * face[2] < 0) b.quad(p[1], p[0], p[3], p[2], a); else b.quad(p[0], p[1], p[2], p[3], a);
}
function polyFill(b: GeoBuilder, poly: V2[], y: number, a: Attr) {
  const tri = earcut(poly);
  const up: V3 = [0, 1, 0];
  for (let i = 0; i < tri.length; i += 3) {
    const P = [poly[tri[i]], poly[tri[i + 1]], poly[tri[i + 2]]].map(([x, z]) => [x, y, z] as V3);
    const cr = (P[1][0] - P[0][0]) * (P[2][2] - P[0][2]) - (P[1][2] - P[0][2]) * (P[2][0] - P[0][0]);
    const uv = P.map((p) => [p[0], -p[2]] as [number, number]);
    if (cr < 0) b.tri(P[0], P[1], P[2], up, up, up, uv[0], uv[1], uv[2], a); else b.tri(P[0], P[2], P[1], up, up, up, uv[0], uv[2], uv[1], a);
  }
}
