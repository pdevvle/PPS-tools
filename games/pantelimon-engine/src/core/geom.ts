// 2D geometry on the ground plane (x east, z south), shared by generators and the game.

export type V2 = [number, number];

export const clamp = (x: number, a: number, b: number): number => (x < a ? a : x > b ? b : x);
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
export const smoothstep = (a: number, b: number, x: number): number => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

export function polyArea(p: V2[]): number {
  let a = 0;
  for (let i = 0; i < p.length; i++) {
    const [x0, z0] = p[i], [x1, z1] = p[(i + 1) % p.length];
    a += x0 * z1 - x1 * z0;
  }
  return a / 2;
}

export function centroid(p: V2[]): V2 {
  let x = 0, z = 0;
  for (const q of p) { x += q[0]; z += q[1]; }
  return [x / p.length, z / p.length];
}

export function pointInPoly(x: number, z: number, p: V2[]): boolean {
  let inside = false;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, zi] = p[i], [xj, zj] = p[j];
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

export function convexHull(pts: V2[]): V2[] {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cross = (o: V2, a: V2, b: V2) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: V2[] = [];
  for (const q of p) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop(); lower.push(q); }
  const upper: V2[] = [];
  for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop(); upper.push(q); }
  upper.pop(); lower.pop();
  return lower.concat(upper);
}

/** Oriented bounding box. angle follows the rotateY convention used everywhere:
 *  world = (lx·cos + lz·sin, −lx·sin + lz·cos) + centre. hx is the half-length along local x (the long axis). */
export interface OBB { cx: number; cz: number; hx: number; hz: number; angle: number }

export function minAreaOBB(poly: V2[]): OBB {
  const hull = convexHull(poly);
  let best: OBB | null = null, bestArea = Infinity;
  for (let i = 0; i < hull.length; i++) {
    const [x0, z0] = hull[i], [x1, z1] = hull[(i + 1) % hull.length];
    const ex = x1 - x0, ez = z1 - z0;
    const len = Math.hypot(ex, ez);
    if (len < 1e-6) continue;
    // local x along the edge: world dir (cos a, −sin a) = (ex, ez)/len  →  a = atan2(−ez, ex)
    const a = Math.atan2(-ez, ex);
    const c = Math.cos(a), s = Math.sin(a);
    let mnx = Infinity, mxx = -Infinity, mnz = Infinity, mxz = -Infinity;
    for (const [x, z] of hull) {
      const lx = x * c - z * s, lz = x * s + z * c;
      if (lx < mnx) mnx = lx; if (lx > mxx) mxx = lx; if (lz < mnz) mnz = lz; if (lz > mxz) mxz = lz;
    }
    const area = (mxx - mnx) * (mxz - mnz);
    if (area < bestArea) {
      bestArea = area;
      const lcx = (mnx + mxx) / 2, lcz = (mnz + mxz) / 2;
      best = { cx: lcx * c + lcz * s, cz: -lcx * s + lcz * c, hx: (mxx - mnx) / 2, hz: (mxz - mnz) / 2, angle: a };
    }
  }
  if (!best) return { cx: poly[0][0], cz: poly[0][1], hx: 1, hz: 1, angle: 0 };
  // keep the long side on local x
  if (best.hz > best.hx) best = { cx: best.cx, cz: best.cz, hx: best.hz, hz: best.hx, angle: best.angle + Math.PI / 2 };
  return best;
}

export function toLocal(o: OBB, x: number, z: number): V2 {
  const dx = x - o.cx, dz = z - o.cz, c = Math.cos(o.angle), s = Math.sin(o.angle);
  return [dx * c - dz * s, dx * s + dz * c];
}
export function toWorld(o: { cx: number; cz: number; angle: number }, lx: number, lz: number): V2 {
  const c = Math.cos(o.angle), s = Math.sin(o.angle);
  return [o.cx + lx * c + lz * s, o.cz - lx * s + lz * c];
}

export interface Rect { x0: number; z0: number; x1: number; z1: number }
export const rectW = (r: Rect) => r.x1 - r.x0;
export const rectD = (r: Rect) => r.z1 - r.z0;

/** Cover a footprint (already in its OBB frame) with a few axis-aligned rectangles:
 *  rasterise at `cell` metres, then repeatedly take the largest rectangle of unclaimed cells. */
export function rectCover(local: V2[], cell: number, minSide: number, coverStop = 0.9): Rect[] {
  let mnx = Infinity, mxx = -Infinity, mnz = Infinity, mxz = -Infinity;
  for (const [x, z] of local) { mnx = Math.min(mnx, x); mxx = Math.max(mxx, x); mnz = Math.min(mnz, z); mxz = Math.max(mxz, z); }
  const nx = Math.max(1, Math.round((mxx - mnx) / cell)), nz = Math.max(1, Math.round((mxz - mnz) / cell));
  const cx = (mxx - mnx) / nx, cz = (mxz - mnz) / nz;
  const g = new Uint8Array(nx * nz);
  let total = 0;
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    if (pointInPoly(mnx + (i + 0.5) * cx, mnz + (j + 0.5) * cz, local)) { g[j * nx + i] = 1; total++; }
  }
  const rects: Rect[] = [];
  let covered = 0;
  const minI = Math.max(1, Math.round(minSide / cx)), minJ = Math.max(1, Math.round(minSide / cz));
  for (let guard = 0; guard < 12 && covered < total * coverStop; guard++) {
    // largest rectangle in a binary matrix (histogram method)
    const h = new Int32Array(nx);
    let best = { area: 0, i0: 0, i1: 0, j0: 0, j1: 0 };
    for (let j = 0; j < nz; j++) {
      for (let i = 0; i < nx; i++) h[i] = g[j * nx + i] === 1 ? h[i] + 1 : 0;
      const st: number[] = [];
      for (let i = 0; i <= nx; i++) {
        const hi = i < nx ? h[i] : 0;
        while (st.length && h[st[st.length - 1]] >= hi) {
          const top = st.pop() as number;
          const height = h[top];
          const left = st.length ? st[st.length - 1] + 1 : 0;
          const width = i - left;
          if (height >= minJ && width >= minI && width * height > best.area) best = { area: width * height, i0: left, i1: i, j0: j - height + 1, j1: j + 1 };
        }
        st.push(i);
      }
    }
    if (best.area === 0) break;
    for (let j = best.j0; j < best.j1; j++) for (let i = best.i0; i < best.i1; i++) g[j * nx + i] = 2;
    covered += best.area;
    rects.push({ x0: mnx + best.i0 * cx, x1: mnx + best.i1 * cx, z0: mnz + best.j0 * cz, z1: mnz + best.j1 * cz });
  }
  if (!rects.length) rects.push({ x0: mnx, x1: mxx, z0: mnz, z1: mxz });
  return rects;
}

/** Ear-clipping triangulation of a simple polygon; returns index triples. */
export function triangulate(p: V2[]): number[] {
  const n = p.length;
  if (n < 3) return [];
  const idx = Array.from({ length: n }, (_, i) => i);
  if (polyArea(p) < 0) idx.reverse();
  const out: number[] = [];
  const isEar = (a: number, b: number, c: number, list: number[]) => {
    const [ax, az] = p[a], [bx, bz] = p[b], [cx, cz] = p[c];
    if ((bx - ax) * (cz - az) - (bz - az) * (cx - ax) <= 0) return false;
    for (const k of list) {
      if (k === a || k === b || k === c) continue;
      const [px, pz] = p[k];
      const d1 = (bx - ax) * (pz - az) - (bz - az) * (px - ax);
      const d2 = (cx - bx) * (pz - bz) - (cz - bz) * (px - bx);
      const d3 = (ax - cx) * (pz - cz) - (az - cz) * (px - cx);
      if (d1 >= 0 && d2 >= 0 && d3 >= 0) return false;
    }
    return true;
  };
  let guard = 0;
  while (idx.length > 3 && guard++ < n * n) {
    let found = false;
    for (let i = 0; i < idx.length; i++) {
      const a = idx[(i + idx.length - 1) % idx.length], b = idx[i], c = idx[(i + 1) % idx.length];
      if (isEar(a, b, c, idx)) { out.push(a, b, c); idx.splice(i, 1); found = true; break; }
    }
    if (!found) break;
  }
  if (idx.length === 3) out.push(idx[0], idx[1], idx[2]);
  return out;
}

export function distToSegment(px: number, pz: number, ax: number, az: number, bx: number, bz: number): number {
  const dx = bx - ax, dz = bz - az;
  const l2 = dx * dx + dz * dz;
  const t = l2 > 0 ? clamp(((px - ax) * dx + (pz - az) * dz) / l2, 0, 1) : 0;
  return Math.hypot(px - (ax + dx * t), pz - (az + dz * t));
}

export function distToPolyline(px: number, pz: number, pts: V2[]): number {
  let d = Infinity;
  for (let i = 0; i < pts.length - 1; i++) d = Math.min(d, distToSegment(px, pz, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]));
  return d;
}

/** Signed distance from a point to the boundary of an OBB (negative inside). */
export function distToOBB(o: OBB, x: number, z: number): number {
  const [lx, lz] = toLocal(o, x, z);
  const dx = Math.abs(lx) - o.hx, dz = Math.abs(lz) - o.hz;
  const ox = Math.max(dx, 0), oz = Math.max(dz, 0);
  return Math.hypot(ox, oz) + Math.min(Math.max(dx, dz), 0);
}
