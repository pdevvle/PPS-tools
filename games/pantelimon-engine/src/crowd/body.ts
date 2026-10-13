// ===================================================================
// The crowd body: one low-poly figure in a neutral pose, each vertex
// tagged with the bone that moves it and the garment it belongs to. The
// GPU poses it (see crowd.ts), so thousands of people share one mesh.
//   aMat  → bone:  0 pelvis, 1 torso, 2 head, 3/4 left upper/fore arm,
//                  5/6 right upper/fore arm, 7/8 left thigh/shin, 9/10 right
//   aAux.x → part: 0 skin, 1 top, 2 bottom, 3 hair, 4 shoes, 5 hat, 6 flag,
//                  7 pole, 8 legs, 9 coat skirt, 10 skirt, 11 carried rug
//   aAux.y → variant within a part (hat style, hair style)
// The figure faces +z, feet at y = 0, about 1.72 m tall.
// ===================================================================
import { GeoBuilder, A, type V3 } from '../mesh/builder';

export const PIVOTS: V3[] = [
  [0, 0.95, 0], [0, 1.02, 0], [0, 1.5, 0],
  [0.2, 1.43, 0], [0.215, 1.14, 0], [-0.2, 1.43, 0], [-0.215, 1.14, 0],
  [0.09, 0.92, 0], [0.09, 0.5, 0], [-0.09, 0.92, 0], [-0.09, 0.5, 0],
];
export const PARENT = [-1, 0, 1, 1, 3, 1, 5, 0, 7, 0, 9];

export function buildBody(): GeoBuilder {
  const b = new GeoBuilder(8192);
  const P = (bone: number, part: number, variant = 0) => A([1, 1, 1], bone, { aux: [part, variant] });
  // legs
  for (const s of [1, -1]) {
    const th = s > 0 ? 7 : 9, sh = s > 0 ? 8 : 10;
    b.tube([s * 0.09, 0.93, 0], [s * 0.09, 0.5, 0.005], 0.078, 0.058, 8, P(th, 8), false);
    b.tube([s * 0.09, 0.5, 0.005], [s * 0.09, 0.1, -0.01], 0.056, 0.042, 8, P(sh, 8), false);
    // shoes: a rounded box toward the toe
    b.push().translate(s * 0.09, 0.0, 0.035);
    b.boxMM(-0.048, 0, -0.07, 0.048, 0.1, 0.12, P(sh, 4));
    b.boxMM(-0.044, 0, 0.12, 0.044, 0.07, 0.165, P(sh, 4));
    b.pop();
  }
  // pelvis
  b.push().translate(0, 0.84, 0).lathe([[0.13, 0], [0.16, 0.08], [0.155, 0.18], [0.0, 0.19]], 10, P(0, 2), 1, 0.72).pop();
  // coat skirt and plain skirt (shown per person)
  b.push().translate(0, 0.42, 0).lathe([[0.25, 0], [0.22, 0.25], [0.18, 0.5], [0.17, 0.62]], 12, P(0, 9), 1, 0.8).pop();
  b.push().translate(0, 0.5, 0).lathe([[0.22, 0], [0.19, 0.25], [0.155, 0.47]], 12, P(0, 10), 1, 0.78).pop();
  // torso: a padded winter shape, wider at the shoulders
  b.push().translate(0, 0.98, 0).lathe([[0.155, 0], [0.17, 0.12], [0.185, 0.3], [0.19, 0.4], [0.14, 0.48], [0.06, 0.52]], 12, P(1, 1), 1, 0.66).pop();
  // collar and neck
  b.push().translate(0, 1.43, 0).lathe([[0.1, 0], [0.085, 0.07], [0.07, 0.08]], 10, P(1, 1), 1, 0.85).pop();
  b.tube([0, 1.47, 0], [0, 1.56, 0.01], 0.05, 0.048, 8, P(2, 0), false);
  // head: a slightly long skull, the face toward +z
  b.push().translate(0, 1.645, 0.012).lathe([[0.0, -0.11], [0.06, -0.1], [0.085, -0.06], [0.098, 0.0], [0.096, 0.05], [0.08, 0.1], [0.04, 0.13], [0.0, 0.135]], 12, P(2, 0), 0.82, 0.95).pop();
  b.box(0, 1.63, 0.1, 0.03, 0.05, 0.03, P(2, 0)); // nose
  for (const s of [1, -1]) b.box(s * 0.083, 1.64, 0.0, 0.02, 0.05, 0.035, P(2, 0)); // ears
  // hair: three styles
  b.push().translate(0, 1.66, -0.005).lathe([[0.09, -0.02], [0.1, 0.03], [0.09, 0.09], [0.05, 0.13], [0.0, 0.145]], 12, P(2, 3, 0), 0.86, 0.98).pop();
  b.push().translate(0, 1.62, -0.03).lathe([[0.095, -0.1], [0.105, 0.0], [0.1, 0.08], [0.06, 0.15], [0.0, 0.17]], 12, P(2, 3, 1), 0.9, 1.0).pop(); // longer, to the collar
  b.push().translate(0, 1.73, -0.06).blob(0.06, P(2, 3, 2), mul(7), 1, 0.8, 1, 0.1).pop(); // a bun
  // hats: 1 flat cap, 2 fur căciulă, 3 knitted hat, 4 headscarf (basma)
  b.push().translate(0, 1.73, 0.0).lathe([[0.105, 0], [0.11, 0.03], [0.1, 0.06], [0.0, 0.07]], 12, P(2, 5, 1), 0.92, 1.0).pop();
  b.boxMM(-0.08, 1.735, 0.06, 0.08, 1.75, 0.15, P(2, 5, 1));
  b.push().translate(0, 1.69, 0).lathe([[0.115, 0], [0.12, 0.08], [0.115, 0.16], [0.0, 0.165]], 12, P(2, 5, 2), 0.95, 1.0).pop();
  b.push().translate(0, 1.7, 0).lathe([[0.108, 0], [0.11, 0.05], [0.09, 0.12], [0.03, 0.155], [0.0, 0.16]], 12, P(2, 5, 3), 0.92, 1.0).pop();
  b.push().translate(0, 1.56, -0.01).lathe([[0.11, 0], [0.115, 0.08], [0.11, 0.16], [0.07, 0.24], [0.0, 0.25]], 12, P(2, 5, 4), 0.95, 1.05).pop();
  // arms and hands
  for (const s of [1, -1]) {
    const ua = s > 0 ? 3 : 5, fa = s > 0 ? 4 : 6;
    b.tube([s * 0.2, 1.44, 0], [s * 0.215, 1.14, 0], 0.058, 0.05, 8, P(ua, 1), true);
    b.tube([s * 0.215, 1.14, 0], [s * 0.22, 0.9, 0.01], 0.05, 0.043, 8, P(fa, 1), true);
    b.push().translate(s * 0.222, 0.85, 0.015).blob(0.042, P(fa, 0), mul(s > 0 ? 3 : 4), 0.7, 1.1, 1.0, 0.08).pop();
  }
  // a flag on a pole, held in the right hand; the pole runs forward (+z) in the rest pose
  b.tube([-0.222, 0.85, -0.6], [-0.222, 0.85, 1.9], 0.016, 0.016, 5, P(6, 7), true);
  for (let i = 0; i < 6; i++) {
    const z0 = 1.85 - i * 0.16, z1 = z0 - 0.16;
    const a = A([1, 1, 1], 6, { aux: [6, i / 6] });
    const p0: V3 = [-0.222, 0.85, z0], p1: V3 = [-0.222, 0.85, z1], p2: V3 = [-0.222 - 0.95, 0.85, z1], p3: V3 = [-0.222 - 0.95, 0.85, z0];
    b.quad(p0, p1, p2, p3, a, [[0, 1 - i / 6], [0, 1 - (i + 1) / 6], [1, 1 - (i + 1) / 6], [1, 1 - i / 6]]);
    b.quad(p0, p3, p2, p1, a, [[0, 1 - i / 6], [1, 1 - i / 6], [1, 1 - (i + 1) / 6], [0, 1 - (i + 1) / 6]]);
  }
  // a rug or quilt shaken out of the window, hanging from both hands
  {
    const a = A([1, 1, 1], 4, { aux: [11, 0] });
    b.quad([0.25, 0.86, 0.06], [-0.25, 0.86, 0.06], [-0.25, 0.86, 0.95], [0.25, 0.86, 0.95], a, [[1, 0], [0, 0], [0, 1], [1, 1]]);
    b.quad([0.25, 0.86, 0.06], [0.25, 0.86, 0.95], [-0.25, 0.86, 0.95], [-0.25, 0.86, 0.06], a, [[1, 0], [1, 1], [0, 1], [0, 0]]);
  }
  return b;
}
function mul(seed: number) { let a = seed * 9973; return () => { a = (a * 16807) % 2147483647; return a / 2147483647; }; }
