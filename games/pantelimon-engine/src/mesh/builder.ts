// ===================================================================
// Geometry builder. Emits flat (non-indexed) triangle soup into typed
// arrays with the attributes the world shader reads. No three.js and no
// DOM, so it runs inside the mesh worker and the output can be
// transferred without copying.
// ===================================================================
import { lin } from './mat';

export type V3 = [number, number, number];
export interface Attr { col: V3; mat: number; seed: number; snow: number; ao: number; aux: [number, number] }
/** The arrays a mesh is made of; every field has `count` entries of its width. */
export interface MeshData {
  count: number;
  position: Float32Array; normal: Float32Array; col: Float32Array; mat: Float32Array;
  uv: Float32Array; seed: Float32Array; snow: Float32Array; ao: Float32Array; aux: Float32Array; bid: Float32Array;
}

export function A(col: string | V3, mat = 0, extra: Partial<Attr> = {}): Attr {
  return { col: typeof col === 'string' ? lin(col) : col, mat, seed: 0, snow: 0, ao: 1, aux: [0, 0], ...extra };
}
export const withA = (a: Attr, extra: Partial<Attr>): Attr => ({ ...a, ...extra });
export const tint = (a: Attr, k: number): Attr => ({ ...a, col: [a.col[0] * k, a.col[1] * k, a.col[2] * k] });

// 3x4 affine matrices, column-major [m0 m3 m6 m9 / m1 m4 m7 m10 / m2 m5 m8 m11]
type Mat = Float64Array;
const ident = (): Mat => Float64Array.of(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0);
function mul(a: Mat, b: Mat): Mat {
  const o = new Float64Array(12);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 3; r++) {
    let s = c === 3 ? a[9 + r] : 0;
    for (let k = 0; k < 3; k++) s += a[k * 3 + r] * b[c * 3 + k];
    o[c * 3 + r] = s;
  }
  return o;
}

class Grow {
  a: Float32Array; n = 0;
  constructor(cap: number) { this.a = new Float32Array(cap); }
  push3(x: number, y: number, z: number) { if (this.n + 3 > this.a.length) this.grow(); this.a[this.n++] = x; this.a[this.n++] = y; this.a[this.n++] = z; }
  push2(x: number, y: number) { if (this.n + 2 > this.a.length) this.grow(); this.a[this.n++] = x; this.a[this.n++] = y; }
  push1(x: number) { if (this.n + 1 > this.a.length) this.grow(); this.a[this.n++] = x; }
  grow() { const b = new Float32Array(this.a.length * 2); b.set(this.a); this.a = b; }
  done() { return this.a.slice(0, this.n); }
}

const TAU = Math.PI * 2;
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scl = (a: V3, k: number): V3 => [a[0] * k, a[1] * k, a[2] * k];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V3): V3 => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
export const v3 = { sub, add, scl, cross, norm };

export class GeoBuilder {
  private P: Grow; private N: Grow; private C: Grow; private Mt: Grow; private UV: Grow; private S: Grow; private Sn: Grow; private AO: Grow; private AX: Grow; private B: Grow;
  private m: Mat = ident();
  private stack: Mat[] = [];
  /** Building id written into every vertex (lets the shader hide a far shell once its detailed version is loaded). */
  bid = -1;
  /** 0 outdoors; 1 an unlit room, 2 a lit room. Written into aSnow as a negative number (interiors never take snow). */
  indoor = 0;
  constructor(cap = 4096) {
    this.P = new Grow(cap * 3); this.N = new Grow(cap * 3); this.C = new Grow(cap * 3); this.Mt = new Grow(cap);
    this.UV = new Grow(cap * 2); this.S = new Grow(cap); this.Sn = new Grow(cap); this.AO = new Grow(cap); this.AX = new Grow(cap * 2); this.B = new Grow(cap);
  }
  get count() { return this.Mt.n; }
  push() { this.stack.push(this.m.slice() as Mat); return this; }
  pop() { this.m = this.stack.pop()!; return this; }
  private apply(t: Mat) { this.m = mul(this.m, t); return this; }
  translate(x: number, y: number, z: number) { return this.apply(Float64Array.of(1, 0, 0, 0, 1, 0, 0, 0, 1, x, y, z)); }
  rotateY(a: number) { const c = Math.cos(a), s = Math.sin(a); return this.apply(Float64Array.of(c, 0, -s, 0, 1, 0, s, 0, c, 0, 0, 0)); }
  rotateX(a: number) { const c = Math.cos(a), s = Math.sin(a); return this.apply(Float64Array.of(1, 0, 0, 0, c, s, 0, -s, c, 0, 0, 0)); }
  rotateZ(a: number) { const c = Math.cos(a), s = Math.sin(a); return this.apply(Float64Array.of(c, s, 0, -s, c, 0, 0, 0, 1, 0, 0, 0)); }
  scale(x: number, y: number, z: number) { return this.apply(Float64Array.of(x, 0, 0, 0, y, 0, 0, 0, z, 0, 0, 0)); }

  vert(p: V3, n: V3, uv: [number, number], a: Attr) {
    const m = this.m;
    this.P.push3(m[0] * p[0] + m[3] * p[1] + m[6] * p[2] + m[9], m[1] * p[0] + m[4] * p[1] + m[7] * p[2] + m[10], m[2] * p[0] + m[5] * p[1] + m[8] * p[2] + m[11]);
    // rotation and uniform scale only, so the linear part transforms normals well enough
    const nx = m[0] * n[0] + m[3] * n[1] + m[6] * n[2], ny = m[1] * n[0] + m[4] * n[1] + m[7] * n[2], nz = m[2] * n[0] + m[5] * n[1] + m[8] * n[2];
    const l = Math.hypot(nx, ny, nz) || 1;
    this.N.push3(nx / l, ny / l, nz / l);
    this.C.push3(a.col[0], a.col[1], a.col[2]); this.Mt.push1(a.mat); this.UV.push2(uv[0], uv[1]);
    this.S.push1(a.seed); this.Sn.push1(this.indoor ? -this.indoor : a.snow); this.AO.push1(a.ao); this.AX.push2(a.aux[0], a.aux[1]); this.B.push1(this.bid);
  }
  tri(p0: V3, p1: V3, p2: V3, n0: V3, n1: V3, n2: V3, uv0: [number, number], uv1: [number, number], uv2: [number, number], a: Attr, a1?: Attr, a2?: Attr) {
    this.vert(p0, n0, uv0, a); this.vert(p1, n1, uv1, a1 || a); this.vert(p2, n2, uv2, a2 || a);
  }
  /** Planar quad, corners counter-clockwise seen from the front. */
  quad(p0: V3, p1: V3, p2: V3, p3: V3, a: Attr, uvs?: [number, number][]) {
    const n = norm(cross(sub(p1, p0), sub(p3, p0)));
    const u = uvs || [[0, 0], [1, 0], [1, 1], [0, 1]];
    this.tri(p0, p1, p2, n, n, n, u[0], u[1], u[2], a);
    this.tri(p0, p2, p3, n, n, n, u[0], u[2], u[3], a);
  }
  /** Vertical rectangle: origin bottom-left as seen from the front, horizontal normal n; u runs along cross(up, n) in metres. */
  facade(ox: number, oy: number, oz: number, n: V3, w: number, h: number, a: Attr, u0 = 0, v0 = 0) {
    const t = norm(cross([0, 1, 0], n));
    const o: V3 = [ox, oy, oz];
    const p1 = add(o, scl(t, w)), p2: V3 = [p1[0], p1[1] + h, p1[2]], p3: V3 = [ox, oy + h, oz];
    this.quad(o, p1, p2, p3, a, [[u0, v0], [u0 + w, v0], [u0 + w, v0 + h], [u0, v0 + h]]);
  }
  /** Horizontal rectangle facing up (or down). */
  flat(x0: number, z0: number, x1: number, z1: number, y: number, a: Attr, down = false, uvScale = 1) {
    const p: V3[] = [[x0, y, z1], [x1, y, z1], [x1, y, z0], [x0, y, z0]];
    const uv = p.map((q) => [q[0] * uvScale, -q[2] * uvScale] as [number, number]);
    if (down) this.quad(p[3], p[2], p[1], p[0], a, [uv[3], uv[2], uv[1], uv[0]]);
    else this.quad(p[0], p[1], p[2], p[3], a, uv);
  }
  /** Axis-aligned box from its centre and size; per-face attrs, or false to skip a face. */
  box(cx: number, cy: number, cz: number, sx: number, sy: number, sz: number, a: Attr, faces: Partial<Record<'px' | 'nx' | 'py' | 'ny' | 'pz' | 'nz', Attr | false>> = {}) {
    const x0 = cx - sx / 2, x1 = cx + sx / 2, y0 = cy - sy / 2, y1 = cy + sy / 2, z0 = cz - sz / 2, z1 = cz + sz / 2;
    const get = (k: keyof typeof faces) => (faces[k] === false ? null : faces[k] || a);
    let q: Attr | null;
    if ((q = get('pz'))) this.facade(x0, y0, z1, [0, 0, 1], sx, sy, q, x0, y0);
    if ((q = get('nz'))) this.facade(x1, y0, z0, [0, 0, -1], sx, sy, q, -x1, y0);
    if ((q = get('px'))) this.facade(x1, y0, z1, [1, 0, 0], sz, sy, q, -z1, y0);
    if ((q = get('nx'))) this.facade(x0, y0, z0, [-1, 0, 0], sz, sy, q, z0, y0);
    if ((q = get('py'))) this.flat(x0, z0, x1, z1, y1, q);
    if ((q = get('ny'))) this.flat(x0, z0, x1, z1, y0, q, true);
    return this;
  }
  /** Box from min/max corners. */
  boxMM(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, a: Attr, faces: Parameters<GeoBuilder['box']>[7] = {}) {
    return this.box((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, x1 - x0, y1 - y0, z1 - z0, a, faces);
  }
  /** Cylinder or cone between two points. */
  tube(p0: V3, p1: V3, r0: number, r1: number, sides: number, a: Attr, caps = true) {
    const ax = sub(p1, p0); const len = Math.hypot(ax[0], ax[1], ax[2]); const axis = norm(ax);
    const tmp: V3 = Math.abs(axis[1]) < 0.95 ? [0, 1, 0] : [1, 0, 0];
    const bx = norm(cross(axis, tmp)), bz = norm(cross(axis, bx));
    const slope = (r0 - r1) / Math.max(len, 1e-4);
    const ring = (i: number) => {
      const t = (i / sides) * TAU, c = Math.cos(t), s = Math.sin(t);
      const d = add(scl(bx, c), scl(bz, s));
      return { d, n: norm(add(d, scl(axis, slope))), u: i / sides };
    };
    const circ = TAU * Math.max(r0, r1);
    for (let i = 0; i < sides; i++) {
      const A0 = ring(i), A1 = ring(i + 1);
      const a0 = add(p0, scl(A0.d, r0)), a1 = add(p0, scl(A1.d, r0)), b0 = add(p1, scl(A0.d, r1)), b1 = add(p1, scl(A1.d, r1));
      const u0 = A0.u * circ, u1 = A1.u * circ;
      this.tri(a0, a1, b1, A0.n, A1.n, A1.n, [u0, 0], [u1, 0], [u1, len], a);
      this.tri(a0, b1, b0, A0.n, A1.n, A0.n, [u0, 0], [u1, len], [u0, len], a);
      if (caps) {
        const na = scl(axis, -1);
        if (r0 > 0.001) this.tri(p0, a1, a0, na, na, na, [0, 0], [0, 0], [0, 0], a);
        if (r1 > 0.001) this.tri(p1, b0, b1, axis, axis, axis, [0, 0], [0, 0], [0, 0], a);
      }
    }
    return this;
  }
  /** Surface of revolution about local y: profile [[radius, y], ...] bottom to top. */
  lathe(profile: [number, number][], sides: number, a: Attr, sx = 1, sz = 1) {
    const nr = profile.map((_, i) => {
      const pa = profile[Math.max(0, i - 1)], pb = profile[Math.min(profile.length - 1, i + 1)];
      const dy = pb[1] - pa[1], dr = pb[0] - pa[0], l = Math.hypot(dy, dr) || 1;
      return [dy / l, -dr / l];
    });
    const P = (i: number, j: number) => {
      const t = (j / sides) * TAU, c = Math.cos(t), s = Math.sin(t);
      return { p: [profile[i][0] * c * sx, profile[i][1], profile[i][0] * s * sz] as V3, n: norm([nr[i][0] * c / sx, nr[i][1], nr[i][0] * s / sz]), uv: [j / sides, profile[i][1]] as [number, number] };
    };
    for (let i = 0; i < profile.length - 1; i++) for (let j = 0; j < sides; j++) {
      const q00 = P(i, j), q01 = P(i, j + 1), q10 = P(i + 1, j), q11 = P(i + 1, j + 1);
      this.tri(q00.p, q11.p, q01.p, q00.n, q11.n, q01.n, q00.uv, q11.uv, q01.uv, a);
      this.tri(q00.p, q10.p, q11.p, q00.n, q10.n, q11.n, q00.uv, q10.uv, q11.uv, a);
    }
    return this;
  }
  /** Low-poly lumpy sphere (foliage, bundles, rocks). */
  blob(r: number, a: Attr, rnd: () => number, sx = 1, sy = 1, sz = 1, rough = 0.25) {
    const t = (1 + Math.sqrt(5)) / 2;
    const V: V3[] = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]].map((v) => norm(v as V3));
    const F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
    const d = V.map(() => 1 + (rnd() - 0.5) * rough * 2);
    const P = V.map((v, i) => [v[0] * r * sx * d[i], v[1] * r * sy * d[i], v[2] * r * sz * d[i]] as V3);
    for (const [i, j, k] of F) {
      const n = norm(cross(sub(P[j], P[i]), sub(P[k], P[i])));
      this.tri(P[i], P[j], P[k], n, n, n, [P[i][0], P[i][1]], [P[j][0], P[j][1]], [P[k][0], P[k][1]], a);
    }
    return this;
  }
  /** Append a finished mesh, transformed by the current matrix. */
  append(md: MeshData) {
    const p = md.position, n = md.normal;
    for (let i = 0; i < md.count; i++) {
      const a: Attr = { col: [md.col[i * 3], md.col[i * 3 + 1], md.col[i * 3 + 2]], mat: md.mat[i], seed: md.seed[i], snow: md.snow[i], ao: md.ao[i], aux: [md.aux[i * 2], md.aux[i * 2 + 1]] };
      this.vert([p[i * 3], p[i * 3 + 1], p[i * 3 + 2]], [n[i * 3], n[i * 3 + 1], n[i * 3 + 2]], [md.uv[i * 2], md.uv[i * 2 + 1]], a);
    }
    return this;
  }
  finish(): MeshData {
    return {
      count: this.Mt.n, position: this.P.done(), normal: this.N.done(), col: this.C.done(), mat: this.Mt.done(),
      uv: this.UV.done(), seed: this.S.done(), snow: this.Sn.done(), ao: this.AO.done(), aux: this.AX.done(), bid: this.B.done(),
    };
  }
}

export const transferables = (m: MeshData): ArrayBuffer[] => [m.position, m.normal, m.col, m.mat, m.uv, m.seed, m.snow, m.ao, m.aux, m.bid].map((a) => a.buffer as ArrayBuffer);
