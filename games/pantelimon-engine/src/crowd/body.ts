// ===================================================================
// The crowd body, after Nightfall Protocol's FigureKit (mockups/base-
// figure.html): every part is a loft of superellipse cross-sections
// from FigureKit's proportion tables, with soft lobes for chest, belly
// and seat; heads are sculpted by FigureKit's displacement terms (eye
// sockets, brow ridge, cheekbones, lips, chin, jaw) with a faceted nose
// and ears; hair is a block whose lower edge follows fringe, ears and
// nape; joints get small faceted blocks.
//
// FigureKit builds one mesh per person. A street needs thousands, so
// here everyone shares one instanced mesh: men's and women's bodies and
// twelve sculpted faces are all in it, tagged, and the vertex shader
// shows the right ones and applies the person's girth, shoulders, hips,
// belly and age (see crowd.ts). Clothes for December 1989 are the lofts
// themselves, inflated for winter bulk.
//
//   aMat  → bone: 0 pelvis, 1 torso, 2 head, 3/4 left upper/fore arm,
//                 5/6 right upper/fore arm, 7/8 left thigh/shin, 9/10 right
//   aAux.x → part: 0 skin, 1 top, 2 bottom, 3 hair, 4 shoes, 5 hat, 6 flag,
//                 7 pole, 8 legs, 9 coat skirt, 10 skirt, 11 carried rug,
//                 12 brows, 13 eyes
//   aAux.y → variant within a part (hat style, hair style)
//   aCol.x → tag: −1 everyone, 0–5 men's faces, 8–13 women's faces,
//                 20 men's body, 21 women's body
//   aCol.y → painted tint on skin (1 = none; lips, sockets, cheeks)
// Faces +z, feet at y = 0, about 1.78 m tall.
// ===================================================================
import { GeoBuilder, A, type V3 } from '../mesh/builder';

const TAU = Math.PI * 2;
// FigureKit's joint positions (male, unscaled): hips 0.952, torso 1.002, shoulders 1.387 at ±0.19, elbows 0.3 below,
// legs at ±0.078 under the hips, knees 0.42 below, ankles 0.39 below that
export const PIVOTS: V3[] = [
  [0, 0.952, 0], [0, 1.002, 0], [0, 1.47, -0.01],
  [0.19, 1.387, -0.006], [0.19, 1.087, -0.006], [-0.19, 1.387, -0.006], [-0.19, 1.087, -0.006],
  [0.078, 0.872, 0], [0.078, 0.452, 0], [-0.078, 0.872, 0], [-0.078, 0.452, 0],
];
export const PARENT = [-1, 0, 1, 1, 3, 1, 5, 0, 7, 0, 9];
export const TAGS = { all: -1, maleBody: 20, femaleBody: 21 } as const;

type Ring = [number, number, number, number?, number?];   // y, half width, half depth, centre z, superellipse exponent
interface Lobe { a: number; y: number; sa: number; sy: number; amp: number }
const pw = (v: number, n: number) => Math.sign(v) * Math.pow(Math.abs(v), 2 / n);
const sm = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t * t * (3 - 2 * t));
const G = (x: number, m: number, s: number) => Math.exp(-((x - m) * (x - m)) / (2 * s * s));

/** A loft of superellipse rings (FigureKit's `loft`/`loftLobes`), emitted with smooth normals. */
function loft(b: GeoBuilder, rings: Ring[], seg: number, attr: (y: number, ang: number) => ReturnType<typeof A>, opt: { lobes?: Lobe[]; at?: V3; sx?: number; sy?: number; sz?: number; disp?: (deg: number, y: number) => number; extraY?: number[]; caps?: boolean } = {}) {
  rings = rings.slice().sort((p, q) => p[0] - q[0]);
  const interp = (y: number): Ring => {
    for (let i = 0; i < rings.length - 1; i++) {
      const P = rings[i], Q = rings[i + 1];
      if (y <= Q[0]) { const t = (y - P[0]) / (Q[0] - P[0] || 1); return [y, P[1] + (Q[1] - P[1]) * t, P[2] + (Q[2] - P[2]) * t, (P[3] ?? 0) + ((Q[3] ?? 0) - (P[3] ?? 0)) * t, (P[4] ?? 2) + ((Q[4] ?? 2) - (P[4] ?? 2)) * t]; }
    }
    return rings[rings.length - 1];
  };
  const ys = [...new Set([...rings.map((r) => r[0]), ...(opt.extraY ?? [])])].sort((p, q) => p - q);
  const R = ys.map(interp);
  const [ox, oy, oz] = opt.at ?? [0, 0, 0], sx = opt.sx ?? 1, sy = opt.sy ?? 1, sz = opt.sz ?? 1;
  const grid: V3[][] = R.map(([y, w, d, cz = 0, n = 2]) => {
    const row: V3[] = [];
    for (let i = 0; i <= seg; i++) {
      const a = (i / seg) * TAU + Math.PI, s = Math.sin(a), c = Math.cos(a);
      const x = w * pw(s, n), z = cz + d * pw(c, n), ang = Math.atan2(s, c);
      let push = 0;
      for (const L of opt.lobes ?? []) { const da = Math.atan2(Math.sin(ang - L.a), Math.cos(ang - L.a)), r2 = (da / L.sa) ** 2 + ((y - L.y) / L.sy) ** 2; if (r2 < 1) push += L.amp * Math.pow(1 - r2, 1.6); }
      if (opt.disp) push += opt.disp((i / seg - 0.5) * 360, y);
      const l = Math.hypot(x, z - cz) || 1;
      row.push([ox + (x + (x / l) * push) * sx, oy + y * sy, oz + (z + ((z - cz) / l) * push) * sz]);
    }
    return row;
  });
  // normals from the grid's two tangents
  const N = grid.map((row, j) => row.map((_, i) => {
    const ip = grid[j][(i + 1) % seg === 0 && i === seg ? 1 : Math.min(seg, i + 1)], im = grid[j][Math.max(0, i - 1)];
    const ia = i === 0 ? grid[j][seg - 1] : im, ib = i === seg ? grid[j][1] : ip;
    const ja = grid[Math.max(0, j - 1)][i], jb = grid[Math.min(grid.length - 1, j + 1)][i];
    const t1 = [ib[0] - ia[0], ib[1] - ia[1], ib[2] - ia[2]], t2 = [jb[0] - ja[0], jb[1] - ja[1], jb[2] - ja[2]];
    const n: V3 = [t1[1] * t2[2] - t1[2] * t2[1], t1[2] * t2[0] - t1[0] * t2[2], t1[0] * t2[1] - t1[1] * t2[0]];
    const l = Math.hypot(n[0], n[1], n[2]) || 1;
    return [n[0] / l, n[1] / l, n[2] / l] as V3;
  }));
  for (let j = 0; j < grid.length - 1; j++) for (let i = 0; i < seg; i++) {
    const a = grid[j][i], b2 = grid[j][i + 1], c = grid[j + 1][i + 1], d = grid[j + 1][i];
    const ang = (i / seg) * TAU + Math.PI;
    const at = attr(R[j][0], Math.atan2(Math.sin(ang), Math.cos(ang)));
    const at2 = attr(R[j + 1][0], Math.atan2(Math.sin(ang), Math.cos(ang)));
    b.tri(a, b2, c, N[j][i], N[j][i + 1], N[j + 1][i + 1], [i / seg, R[j][0]], [(i + 1) / seg, R[j][0]], [(i + 1) / seg, R[j + 1][0]], at, at, at2);
    b.tri(a, c, d, N[j][i], N[j + 1][i + 1], N[j + 1][i], [i / seg, R[j][0]], [(i + 1) / seg, R[j + 1][0]], [i / seg, R[j + 1][0]], at, at2, at2);
  }
}
/** FigureKit's faceted joint block. */
function block(b: GeoBuilder, at: V3, r: V3, a: ReturnType<typeof A>) {
  b.push().translate(at[0], at[1], at[2]).scale(r[0], r[1], r[2]);
  const rows = 3, seg = 5;
  for (let j = 0; j < rows; j++) for (let i = 0; i < seg; i++) {
    const P = (jj: number, ii: number): V3 => { const t = (jj / rows) * Math.PI, p = (ii / seg) * TAU; return [Math.sin(t) * Math.sin(p), Math.cos(t), Math.sin(t) * Math.cos(p)]; };
    const p0 = P(j, i), p1 = P(j + 1, i), p2 = P(j + 1, i + 1), p3 = P(j, i + 1);
    const n = norm3([p0[0] + p1[0] + p2[0] + p3[0], p0[1] + p1[1] + p2[1] + p3[1], p0[2] + p1[2] + p2[2] + p3[2]]);
    b.tri(p0, p1, p2, n, n, n, [0, 0], [0, 0], [0, 0], a);
    b.tri(p0, p2, p3, n, n, n, [0, 0], [0, 0], [0, 0], a);
  }
  b.pop();
}
const norm3 = (v: V3): V3 => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
function rng(seed: number) { let x = seed >>> 0 || 1; return () => { x = (Math.imul(x, 1664525) + 1013904223) >>> 0; return x / 4294967296; }; }

// ---------------------------------------------------------------- faces (FigureKit's genFace values, Romanian-range colouring is per person)
export interface Face { w: number; d: number; len: number; jaw: number; chinFwd: number; chin: number; brow: number; cheek: number; cheekY: number; eyeY: number; eyeA: number; socket: number; noseL: number; noseW: number; noseT: number; hump: boolean; lipU: number; lipL: number; mouthW: number; forehead: number; ear: number }
export function genFace(seed: number, fem: boolean): Face {
  const r = rng(seed * 2654435761 + 7), R = (a: number, b: number) => a + (b - a) * r(), k = fem ? 0.6 : 1;
  return {
    w: R(0.9, 1.1), d: R(0.95, 1.06), len: R(0.93, 1.07), jaw: R(0.82, 1.2) * (fem ? 0.93 : 1), chinFwd: R(-0.008, 0.01), chin: R(0.002, 0.011) * k,
    brow: R(0.002, 0.011) * k + 0.001, cheek: R(0.002, 0.011), cheekY: R(0.09, 0.106), eyeY: R(0.112, 0.124), eyeA: R(16, 22), socket: R(0.007, 0.014),
    noseL: R(0.88, 1.16), noseW: R(0.8, 1.15), noseT: R(0.85, 1.35), hump: r() < 0.28, lipU: R(0.002, 0.004) + (fem ? 0.0015 : 0), lipL: R(0.0028, 0.0048) + (fem ? 0.0015 : 0),
    mouthW: R(0.9, 1.12), forehead: R(-0.008, 0.006), ear: R(0.88, 1.15),
  };
}
const FACE_SEEDS = [20481, 3307, 911, 77123, 5150, 4242];

/** FigureKit's sculpted head: a profile loft displaced by the face's features. Origin at the chin's underside. */
function sculptHead(b: GeoBuilder, F: Face, tag: number, fem: boolean) {
  const prof: [number, number, number, number][] = [[0, .02, .015, .066], [.008, .034, .03, .062], [.025, .05, .06, .045], [.045, .062, .08, .03], [.065, .068, .09, .02], [.09, .072, .096, .012], [.115, .074, .098, .008], [.135, .076, .1, .006], [.16, .077, .101, .003], [.185, .075, .1, 0], [.205, .068, .094, -.004], [.222, .055, .08, -.008], [.233, .035, .055, -.01], [.238, .01, .015, -.012], [.2395, .001, .001, -.012]];
  const ys = [0, .008, .016, .025, .033, .04, .046, .052, .058, .065, .072, .08, .088, .096, .104, .112, .12, .128, .136, .145, .155, .165, .175, .187, .2, .212, .222, .23, .235, .2385, .2395];
  const fw = fem ? 0.95 : 1;
  const rings: Ring[] = ys.map((y) => {
    let i = 0; while (i < prof.length - 2 && prof[i + 1][0] < y) i++;
    const a = prof[i], c = prof[i + 1], t = Math.min(1, Math.max(0, (y - a[0]) / (c[0] - a[0])));
    let w = a[1] + (c[1] - a[1]) * t, d = a[2] + (c[2] - a[2]) * t, cz = a[3] + (c[3] - a[3]) * t;
    w *= F.w * fw * (1 + (F.jaw - 1) * sm(1 - y / 0.085)); d *= F.d;
    cz += F.chinFwd * sm(1 - y / 0.04) + F.forehead * sm((y - 0.16) / 0.08);
    return [y * F.len, w, d, cz, 2.3];
  });
  const disp = (adeg: number, yy: number) => {
    const y = yy / F.len, A2 = Math.abs(adeg);
    return -F.socket * G(A2, F.eyeA, 8) * G(y, F.eyeY, 0.011) + F.brow * G(A2, F.eyeA - 5, 16) * G(y, F.eyeY + 0.019, 0.007) + 0.004 * G(A2, 0, 8) * G(y, 0.104, 0.022)
      + F.cheek * G(A2, 38, 12) * G(y, F.cheekY, 0.012) - 0.005 * G(A2, 48, 12) * G(y, 0.062, 0.013) + 0.006 * G(A2, 0, 22 * F.mouthW) * G(y, 0.054, 0.016)
      + F.lipU * G(A2, 0, 11 * F.mouthW) * G(y, 0.058, 0.004) - 0.003 * G(A2, 0, 12 * F.mouthW) * G(y, 0.051, 0.0035) + F.lipL * G(A2, 0, 11 * F.mouthW) * G(y, 0.045, 0.004)
      - 0.003 * G(A2, 0, 12) * G(y, 0.034, 0.004) + F.chin * G(A2, 0, 15) * G(y, 0.016, 0.009) - 0.004 * G(A2, 68, 12) * G(y, 0.155, 0.02) + 0.004 * (F.jaw - 0.8) * G(A2, 74, 10) * G(y, 0.032, 0.012);
  };
  // painted tint: shadowed sockets, redder lips and cheeks
  const tint = (yy: number, ang: number) => {
    const y = yy / F.len, adeg = Math.abs((ang * 180) / Math.PI);
    const lips = G(adeg, 0, 12 * F.mouthW) * G(y, 0.051, 0.007) * (fem ? 0.32 : 0.2);
    const sock = G(adeg, F.eyeA, 10) * G(y, F.eyeY, 0.014) * 0.28;
    const cheek = G(adeg, 34, 14) * G(y, F.cheekY - 0.01, 0.018) * 0.12;
    return A([tag, 1 - sock - lips * 0.4 + cheek * 0.2, lips + cheek], 2, { aux: [0, 0] });
  };
  loft(b, rings, 20, tint, { at: [0, 1.542, 0.008], disp });
  // nose: FigureKit's faceted planes (bridge, tip, wings)
  const root = F.eyeY + 0.012, Y = (y: number) => 1.542 + (root - (root - y) * F.noseL) * F.len, Xw = (x: number) => x * F.noseW * fw, Zt = (z: number) => 0.008 + 0.096 * F.d + z * F.noseT;
  const Rt: V3 = [0, Y(.13), Zt(-.004)], Mb: V3 = [0, Y(.105), Zt(.011) + (F.hump ? .004 : 0)], T: V3 = [0, Y(.084), Zt(.024)], U: V3 = [0, Y(.077), Zt(.018)], B: V3 = [0, Y(.073), Zt(.004)];
  const TL: V3 = [Xw(-.009), Y(.124), Zt(-.006)], TR: V3 = [Xw(.009), Y(.124), Zt(-.006)], ML: V3 = [Xw(-.011), Y(.1), Zt(.003)], MR: V3 = [Xw(.011), Y(.1), Zt(.003)], AL: V3 = [Xw(-.016), Y(.078), Zt(-.002)], AR: V3 = [Xw(.016), Y(.078), Zt(-.002)];
  const nose = A([tag, 1, 0.08], 2, { aux: [0, 0] });
  const inside: V3 = [0, 1.62, 0.0];
  for (const [p, q, s] of [[TL, Rt, Mb], [Rt, TR, Mb], [TL, Mb, ML], [ML, Mb, T], [ML, T, AL], [AL, T, U], [AL, U, B], [TR, MR, Mb], [MR, T, Mb], [MR, AR, T], [AR, U, T], [AR, B, U]] as V3[][]) {
    const e1 = [q[0] - p[0], q[1] - p[1], q[2] - p[2]], e2 = [s[0] - p[0], s[1] - p[1], s[2] - p[2]];
    let n = norm3([e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]);
    const cx = (p[0] + q[0] + s[0]) / 3 - inside[0], cy = (p[1] + q[1] + s[1]) / 3 - inside[1], cz = (p[2] + q[2] + s[2]) / 3 - inside[2];
    if (n[0] * cx + n[1] * cy + n[2] * cz < 0) { n = [-n[0], -n[1], -n[2]]; b.tri(p, s, q, n, n, n, [0, 0], [0, 0], [0, 0], nose); } else b.tri(p, q, s, n, n, n, [0, 0], [0, 0], [0, 0], nose);
  }
  // ears
  const ear = A([tag, 0.92, 0.1], 2, { aux: [0, 0] });
  for (const s of [-1, 1]) block(b, [s * 0.075 * F.w * fw, 1.542 + (F.eyeY - 0.012) * F.len, -0.008], [0.009 * F.ear, 0.03 * F.ear, 0.018 * F.ear], ear);
  // eyes and brows: small dark almonds under the brow, a stroke of hair above
  const eyeY = 1.542 + F.eyeY * F.len;
  for (const s of [-1, 1]) {
    const ex = s * Math.sin((F.eyeA * Math.PI) / 180) * 0.084 * F.w * fw, ez = 0.008 + Math.cos((F.eyeA * Math.PI) / 180) * 0.093 * F.d - F.socket * 0.6;
    block(b, [ex, eyeY, ez], [0.0115, 0.0055, 0.004], A([tag, 1, 0], 2, { aux: [13, 0] }));
    b.push().translate(ex * 1.04, eyeY + 0.017, ez + 0.004).rotateZ(-s * 0.12).box(0, 0, 0, 0.026, fem ? 0.004 : 0.006, 0.006, A([tag, 1, 0], 2, { aux: [12, 0] })).pop();
  }
}

/** Hair as FigureKit's hair block: the bottom edge drops from fringe to ears to nape. */
function hairBlock(b: GeoBuilder, F: Face, tag: number, style: number, fem: boolean) {
  const fw = (fem ? 0.95 : 1) * F.w, L = F.len, base = 1.542;
  const edges = style === 0 ? [.192, .142, .1, .07] : style === 1 ? [.185, .07, .02, -.03] : [.19, .13, .1, .08];
  const rings: Ring[] = style === 1
    ? [[.196, .084, .108, .004, 2.5], [.214, .081, .105, .002, 2.5], [.227, .069, .092, -.002, 2.3], [.236, .046, .066, -.006, 2.2], [.242, .012, .018, -.01], [.2435, .002, .002, -.01]]
    : [[.198, .081, .106, .006, 2.5], [.214, .078, .103, .004, 2.5], [.227, .066, .09, 0, 2.3], [.236, .044, .064, -.006, 2.2], [.242, .012, .018, -.01], [.2435, .002, .002, -.01]];
  const a = A([tag, 1, 0], 2, { aux: [3, style] });
  const seg = 12;
  const all: [number | null, number, number, number, number][] = [[null, rings[0][1], rings[0][2], rings[0][3] ?? 0, rings[0][4] ?? 2], ...rings.map((r) => [r[0], r[1], r[2], r[3] ?? 0, r[4] ?? 2] as [number, number, number, number, number])];
  const grid: V3[][] = all.map(([y, w, d, cz, n], j) => {
    const row: V3[] = [];
    for (let i = 0; i <= seg; i++) {
      const ang = (i / seg) * TAU + Math.PI, c = Math.cos(ang);
      const yy = j === 0 ? (c > 0.6 ? edges[0] : c > -0.1 ? edges[1] : c > -0.8 ? edges[2] : edges[3]) : (y as number);
      // long hair hangs straighter and a little wider at the bottom
      const grow = j === 0 && style === 1 ? 1.08 : 1;
      row.push([w * pw(Math.sin(ang), n) * fw * grow * 1.03, base + yy * L, 0.008 + (cz + d * pw(c, n)) * F.d * 1.03 * grow]);
    }
    return row;
  });
  for (let j = 0; j < grid.length - 1; j++) for (let i = 0; i < seg; i++) {
    const p = grid[j][i], q = grid[j][i + 1], r2 = grid[j + 1][i + 1], s = grid[j + 1][i];
    const n = norm3([(p[0] + q[0]) / 2, 0.4, (p[2] + q[2]) / 2 - 0.0]);
    b.tri(p, q, r2, n, n, n, [0, 0], [0, 0], [0, 0], a);
    b.tri(p, r2, s, n, n, n, [0, 0], [0, 0], [0, 0], a);
  }
  if (style === 2) block(b, [0, base + 0.2 * L, -0.085 * F.d], [0.045, 0.04, 0.04], a); // a bun
}

export function buildBody(): GeoBuilder {
  const b = new GeoBuilder(32768);
  const P = (bone: number, part: number, tag: number, variant = 0) => () => A([tag, 1, 0], bone, { aux: [part, variant] });
  for (const fem of [false, true]) {
    const tag = fem ? TAGS.femaleBody : TAGS.maleBody;
    const f = fem ? 0.88 : 1, h = fem ? 1.08 : 1;
    // torso: FigureKit's rings, inflated for a winter coat, with soft chest lobes
    const TR: Ring[] = [[-.01, .124 * h, .086], [.06, .118 * (fem ? .92 : 1), .084], [.14, .128 * (fem ? .95 : 1), .09, .004], [.22, .148 * f, .1, .012], [.28, .162 * f, fem ? .104 : .108, fem ? .014 : .02], [.335, .172 * f, .1, .012], [.37, .184 * f, .094, .008], [.395, .19 * f, .086, .002], [.418, .172 * f, .075, -.004], [.442, .13 * f, .065, -.006], [.462, .088 * f, .058, -.008], [.48, .06, .052, -.008]];
    const coat = TR.map(([y, w, d, cz]) => [y, w + 0.022, d + 0.024, cz ?? 0, 2.2] as Ring);
    const chest: Lobe[] = fem ? [-1, 1].map((s) => ({ a: s * 0.5, y: 0.285, sa: 0.62, sy: 0.06, amp: 0.022 })) : [-1, 1].map((s) => ({ a: s * 0.52, y: 0.325, sa: 0.75, sy: 0.05, amp: 0.007 }));
    loft(b, coat, 14, P(1, 1, tag), { at: [0, 1.002, 0], lobes: chest, extraY: [0.1, 0.2, 0.25, 0.3, 0.35] });
    // a turned-up collar
    loft(b, [[.43, .1, .085, -.004, 2.3], [.5, .085, .075, -.006, 2.3], [.52, .07, .06, -.006]], 12, P(1, 1, tag), { at: [0, 1.002, 0] });
    // pelvis (trousers), with the seat as a lobe
    const PR: Ring[] = [[-.18, .03, .034, .004], [-.16, .08 * h, .07, .004], [-.12, .13 * h, .088], [-.06, .14 * h, .095, -.006], [0, .135 * h, .09], [.06, .13 * h, .088]];
    loft(b, PR.map(([y, w, d, cz]) => [y, w + 0.01, d + 0.01, cz ?? 0] as Ring), 12, P(0, 2, tag), { at: [0, 0.952, 0], lobes: [-1, 1].map((s) => ({ a: Math.PI + s * 0.48, y: fem ? -0.065 : -0.075, sa: 0.7, sy: 0.06, amp: fem ? 0.018 : 0.012 })), extraY: [-0.09, -0.07, -0.05] });
    // a coat's skirt to the knee, and a plain skirt
    loft(b, [[-0.5, 0.2 * h, 0.15, 0, 2.2], [-0.25, 0.17 * h, 0.13, 0, 2.2], [0, 0.155 * h, 0.118, 0, 2.2], [0.06, 0.15 * h, 0.115, 0, 2.2]], 14, P(0, 9, tag), { at: [0, 0.952, 0] });
    loft(b, [[-0.45, 0.19 * h, 0.15, 0, 2.2], [-0.2, 0.165 * h, 0.125, 0, 2.2], [0.02, 0.145 * h, 0.105, 0, 2.2]], 14, P(0, 10, tag), { at: [0, 0.952, 0] });
    // neck
    loft(b, [[0, .078 * f, .066, -.006, 2.5], [.05, .067 * f, .061, -.006, 2.5], [.1, .062 * f, .059, -.006, 2.5], [.15, .058 * f, .057, -.008, 2.5]], 8, P(2, 0, tag), { at: [0, 1.402, 0] });
    for (const s of [1, -1]) {
      const ua = s > 0 ? 3 : 5, fa = s > 0 ? 4 : 6, sx = s * (fem ? 0.175 : 0.19);
      // sleeves: FigureKit's arm rings, a little fuller
      loft(b, [[-.3, .034, .034], [-.28, .042 * f + .01, .044 + .01], [-.18, .047 * f + .01, .051 + .01, .003], [-.08, .05 * f + .01, .054 + .01], [-.02, .052 * f + .01, .054 + .01], [.012, .046 * f + .01, .05 + .01], [.03, .03, .036], [.036, .006, .008]], 8, P(ua, 1, tag), { at: [sx, 1.387, -0.006] });
      loft(b, [[.03, .024, .024], [.015, .044 * f + .008, .044 + .008], [-.04, .05 * f + .008, .049 + .008], [-.12, .043 * f + .008, .041 + .008], [-.2, .036 * f + .009, .032 + .009], [-.235, .038 * f + .01, .034 + .01], [-.245, .02, .02]], 8, P(fa, 1, tag), { at: [sx, 1.087, -0.006] });
      block(b, [sx, 1.087, -0.006], [0.05, 0.046, 0.05], P(fa, 1, tag)());
      // hand and thumb, bare
      loft(b, [[-.19, .006, .015], [-.16, .011, .028], [-.09, .014, .04 * f], [-.03, .016, .042 * f], [.005, .014, .03], [.015, .008, .015]], 6, P(fa, 0, tag), { at: [sx, 0.837, -0.002] });
      block(b, [sx, 0.841, -0.006], [0.024, 0.02, 0.026], P(fa, 0, tag)());
      loft(b, [[-.05, .008, .008], [-.025, .011, .011], [0, .012, .012], [.006, .004, .004]], 6, P(fa, 0, tag), { at: [sx - s * 0.006, 0.807, 0.03] });
      // legs: trousers or stockings over FigureKit's thigh and shin
      const th = s > 0 ? 7 : 9, sh = s > 0 ? 8 : 10, lx = s * (fem ? 0.082 : 0.078);
      loft(b, [[.06, .034, .034], [.04, .068 * h + .006, .07 + .006], [0, .08 * h + .006, .084 + .006, .004], [-.12, .077 * h + .006, .081 + .006, .008], [-.26, .068 + .006, .072 + .006, .006], [-.37, .055 + .006, .058 + .006, .004], [-.42, .05 + .006, .052 + .006], [-.44, .03, .03]], 9, P(th, 8, tag), { at: [lx, 0.872, 0] });
      loft(b, [[.035, .03, .03], [.01, .05 + .005, .053 + .005], [-.06, .053 * f + .006, .059 + .006, -.008], [-.14, .05 * f + .006, .057 + .006, -.012], [-.22, .041 + .006, .045 + .006, -.006], [-.31, .036 + .008, .036 + .008], [-.36, .042, .042], [-.38, .02, .02]], 9, P(sh, 8, tag), { at: [lx, 0.452, 0] });
      block(b, [lx, 0.457, 0.006], [0.054, 0.056, 0.058], P(sh, 8, tag)());
      // winter shoes and boots: FigureKit's foot outline, built up into a shoe
      const shoe = P(sh, 4, tag)();
      const S: [number, number, number][] = [[-.06, .03, .03], [-.05, .036, .075], [-.02, .04, .095], [.02, .042, .085], [.06, .046, .06], [.1, .048, .045], [.13, .044, .035], [.155, .036, .028], [.168, .022, .02]];
      const rings: Ring[] = S.map(([z, hw, ht]) => [z, hw * (fem ? 0.9 : 1), ht / 2, 0, 2.6]);
      b.push().translate(lx, 0.0, 0.02).rotateX(Math.PI / 2);
      loft(b, rings.map(([y, w, d]) => [y, w, d, -d, 2.6] as Ring), 8, () => shoe, {});
      b.pop();
    }
  }
  // twelve heads: six men, six women, each with its own hair blocks
  for (const fem of [false, true]) for (let i = 0; i < 6; i++) {
    const tag = (fem ? 8 : 0) + i;
    const F = genFace(FACE_SEEDS[i] + (fem ? 101 : 0), fem);
    sculptHead(b, F, tag, fem);
    for (const style of [0, 1, 2]) hairBlock(b, F, tag, style, fem);
  }
  // hats sized to the largest heads: 1 flat cap, 2 fur căciulă, 3 knitted hat, 4 headscarf (basma)
  const H = (v: number) => () => A([-1, 1, 0], 2, { aux: [5, v] });
  loft(b, [[0, .106, .118, .004], [.03, .11, .12, .002], [.06, .1, .11, -.002], [.07, .02, .02, -.004]], 12, H(1), { at: [0, 1.735, 0.006] });
  b.boxMM(-0.08, 1.738, 0.08, 0.08, 1.752, 0.17, H(1)());
  loft(b, [[0, .115, .125, 0], [.08, .12, .13, 0], [.16, .116, .125, 0], [.165, .01, .01, 0]], 12, H(2), { at: [0, 1.7, 0.006] });
  loft(b, [[0, .108, .118, .004], [.05, .11, .12, .002], [.12, .09, .1, -.004], [.155, .03, .035, -.006], [.16, .002, .002, -.006]], 12, H(3), { at: [0, 1.71, 0.006] });
  loft(b, [[-.02, .09, .1, -.01], [.05, .108, .118, -.004], [.13, .112, .124, 0], [.2, .1, .11, -.002], [.25, .05, .06, -.006], [.26, .002, .002, -.006]], 12, H(4), { at: [0, 1.56, 0.006] });
  // a flag on a pole in the right hand; the pole runs forward (+z) in the rest pose
  const hx = -0.19, hy = 0.77;
  b.tube([hx, hy, -0.6], [hx, hy, 1.9], 0.016, 0.016, 5, A([-1, 1, 0], 6, { aux: [7, 0] }), true);
  for (let i = 0; i < 6; i++) {
    const z0 = 1.85 - i * 0.16, z1 = z0 - 0.16;
    const a = A([-1, 1, 0], 6, { aux: [6, i / 6] });
    const p0: V3 = [hx, hy, z0], p1: V3 = [hx, hy, z1], p2: V3 = [hx - 0.95, hy, z1], p3: V3 = [hx - 0.95, hy, z0];
    b.quad(p0, p1, p2, p3, a); b.quad(p0, p3, p2, p1, a);
  }
  // a rug shaken out of a window, hanging from both hands
  const rug = A([-1, 1, 0], 4, { aux: [11, 0] });
  b.quad([0.25, 0.78, 0.06], [-0.25, 0.78, 0.06], [-0.25, 0.78, 0.95], [0.25, 0.78, 0.95], rug);
  b.quad([0.25, 0.78, 0.06], [0.25, 0.78, 0.95], [-0.25, 0.78, 0.95], [-0.25, 0.78, 0.06], rug);
  return b;
}
