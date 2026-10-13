// ===================================================================
// Furniture models: one function per FurnitureItem type. Each model is
// built at the origin with its width along x, its front facing +z and its
// base at y = 0 (ceiling fittings hang down from y = 0), then placed by
// the item's position and rotation. Plain boxes, tubes and lathes, kept
// low-poly; the world shader paints wood grain, fabric and tiles.
// ===================================================================
import type { FurnitureItem, Room } from '../data/schema';
import { GeoBuilder, A, tint, type Attr, type V3 } from './builder';
import { M } from './mat';

type Draw = (b: GeoBuilder, it: FurnitureItem, room: Room, g: GeoBuilder | null) => void;

const WOODS = ['#4a2e1c', '#5c3a22', '#6a4428', '#3a2416'];         // the dark polished 'mobilă' of the period
const VENEER = ['#8a6a44', '#7a5a3a', '#9a7a52'];
const FABRIC = ['#6a4a3a', '#4a5a4a', '#6a5a3a', '#5a3a3a', '#4a4a5a', '#7a6a4a'];
const ENAMEL = ['#d8d4c8', '#e0dcd0', '#cfd4d0'];
const pick = <T,>(a: T[], v: number) => a[Math.abs(Math.floor(v)) % a.length];
const rng = (seed: number) => { let s = (Math.floor(Math.abs(seed) * 9973) % 2147483646) + 1; return () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; };
const wood = (it: FurnitureItem, k = 0) => A(pick(WOODS, it.variant + k), M.WOOD, { seed: (it.x * 7.1 + it.z * 3.3) % 1 });
const legs = (b: GeoBuilder, w: number, d: number, h: number, a: Attr, r = 0.02, inset = 0.05) => {
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.boxMM(sx * (w / 2 - inset) - r, 0, sz * (d / 2 - inset) - r, sx * (w / 2 - inset) + r, h, sz * (d / 2 - inset) + r, a);
};

const MODELS: Record<string, Draw> = {
  // ---------------- living room
  wallunit(b, it) {
    // the 'bibliotecă' wall unit: glass-fronted vitrine, drop-down bar, the TV niche, books
    const w = 2.6, d = 0.45, h = 2.1, a = wood(it);
    b.boxMM(-w / 2, 0, -d / 2, w / 2, 0.08, d / 2, tint(a, 0.7));
    b.boxMM(-w / 2, 0.08, -d / 2, w / 2, h, -d / 2 + 0.02, a);
    for (const x of [-w / 2, -w / 6, w / 6, w / 2 - 0.02]) b.boxMM(x, 0.08, -d / 2, x + 0.02, h, d / 2, a);
    b.boxMM(-w / 2, h - 0.03, -d / 2, w / 2, h, d / 2, a);
    // lower cupboards
    b.boxMM(-w / 2, 0.08, d / 2 - 0.02, w / 2, 0.8, d / 2, a);
    for (let i = 0; i < 6; i++) b.box(-w / 2 + (i + 0.5) * (w / 6), 0.7, d / 2 + 0.01, 0.06, 0.012, 0.012, A('#b0a070', M.CHROME));
    // middle: open shelf with books and a crystal bowl, then the vitrine with glasses
    b.boxMM(-w / 2, 0.8, -d / 2, w / 2, 0.83, d / 2, a);
    b.boxMM(-w / 2, 1.3, -d / 2, w / 2, 1.33, d / 2, a);
    const bookCols = ['#6a2a1a', '#2a3a5a', '#4a4a2a', '#5a1a1a', '#2a4a3a', '#7a6a4a', '#3a2a4a'];
    let x = w / 6 + 0.04;
    let k = Math.floor(it.x * 13) & 7;
    while (x < w / 2 - 0.08) { const bw = 0.025 + ((k * 37) % 5) * 0.008, bh = 0.2 + ((k * 13) % 4) * 0.025; b.boxMM(x, 0.83, -0.16, x + bw, 0.83 + bh, 0.08, A(bookCols[k % bookCols.length], M.PAINT, { seed: k / 9 })); x += bw + 0.003; k++; }
    for (let i = 0; i < 5; i++) b.tube([-w / 2 + 0.15 + i * 0.13, 1.33, 0.02], [-w / 2 + 0.15 + i * 0.13, 1.45, 0.02], 0.025, 0.035, 6, A('#8a9a9a', M.CHROME));
    b.boxMM(-w / 2 + 0.02, 1.33, d / 2 - 0.01, -w / 6, h - 0.03, d / 2, A('#000000', M.GLASS));
    b.boxMM(w / 6 + 0.02, 1.33, d / 2 - 0.02, w / 2 - 0.02, h - 0.03, d / 2, a);
    // crocheted doily and a porcelain figurine
    b.boxMM(-0.3, 0.83, -0.1, 0.3, 0.834, 0.15, A('#e0dcd0', M.LACE, { seed: 0.2 }));
    b.push().translate(0, 0.834, 0.02).lathe([[0.0, 0], [0.05, 0.01], [0.04, 0.08], [0.06, 0.14], [0.0, 0.16]], 8, A('#c8c4b8', M.PAINT)).pop();
  },
  sofa(b, it) {
    const w = 2.0, d = 0.86, f = A(pick(FABRIC, it.variant), M.UPHOLSTERY, { seed: it.variant * 0.13 });
    b.boxMM(-w / 2, 0.1, -d / 2, w / 2, 0.42, d / 2, f);
    b.boxMM(-w / 2, 0.42, -d / 2, w / 2, 0.85, -d / 2 + 0.2, f);
    for (const s of [-1, 1]) b.boxMM(s > 0 ? w / 2 - 0.14 : -w / 2, 0.1, -d / 2, s > 0 ? w / 2 : -w / 2 + 0.14, 0.62, d / 2, f);
    for (const s of [-1, 1]) b.boxMM(s * 0.45 - 0.42, 0.42, -d / 2 + 0.2, s * 0.45 + 0.42, 0.52, d / 2 - 0.02, tint(f, 1.05));
    legs(b, w, d, 0.1, A('#2a1a10', M.WOOD), 0.02, 0.08);
    // a crocheted runner over the back
    b.boxMM(-0.4, 0.85, -d / 2, 0.4, 0.856, -d / 2 + 0.2, A('#e0dace', M.LACE));
  },
  armchair(b, it) {
    const w = 0.8, d = 0.8, f = A(pick(FABRIC, it.variant + 1), M.UPHOLSTERY, { seed: 0.3 });
    b.boxMM(-w / 2, 0.12, -d / 2, w / 2, 0.42, d / 2, f);
    b.boxMM(-w / 2, 0.42, -d / 2, w / 2, 0.85, -d / 2 + 0.16, f);
    for (const s of [-1, 1]) b.boxMM(s > 0 ? w / 2 - 0.1 : -w / 2, 0.12, -d / 2, s > 0 ? w / 2 : -w / 2 + 0.1, 0.6, d / 2, f);
    legs(b, w, d, 0.12, A('#2a1a10', M.WOOD), 0.018, 0.06);
  },
  coffeetable(b, it) {
    const a = wood(it, 1);
    b.boxMM(-0.5, 0.44, -0.3, 0.5, 0.48, 0.3, a); legs(b, 1.0, 0.6, 0.44, a, 0.02);
    b.boxMM(-0.25, 0.48, -0.18, 0.25, 0.483, 0.18, A('#e0dcd0', M.LACE));
    // cut-glass ashtray
    b.push().translate(0.2, 0.483, 0.05).lathe([[0.0, 0], [0.07, 0], [0.08, 0.03], [0.05, 0.03], [0.0, 0.015]], 8, A('#8a9a9a', M.CHROME)).pop();
  },
  tv(b, it, room) {
    // a 'Diamant' or 'Cromatic' set on its own little table: wooden cabinet, curved grey screen
    const on = !!it.on;
    const a = A(pick(['#3a2a1e', '#5a4632', '#2a2a2a'], it.variant), M.WOOD, { seed: 0.4 });
    legs(b, 0.6, 0.45, 0.5, A('#2a1a10', M.WOOD), 0.015, 0.04);
    b.boxMM(-0.3, 0.48, -0.22, 0.3, 0.52, 0.22, a);
    b.boxMM(-0.3, 0.52, -0.22, 0.3, 1.0, 0.18, a);
    b.boxMM(-0.18, 0.56, -0.32, 0.18, 0.96, -0.22, tint(a, 0.8));
    // screen on the left, controls on the right
    b.boxMM(-0.26, 0.58, 0.18, 0.12, 0.94, 0.2, A('#20221e', M.SCREEN, { seed: (it.x * 3.7) % 1, aux: [on ? 1 : 0, room.lit ? 1 : 0] }));
    for (let i = 0; i < 4; i++) b.tube([0.2, 0.86 - i * 0.07, 0.18], [0.2, 0.86 - i * 0.07, 0.205], 0.015, 0.015, 6, A('#b0a890', M.CHROME));
    b.boxMM(0.15, 0.6, 0.18, 0.27, 0.66, 0.185, A('#4a4038', M.CLOTH));
    // rabbit-ear aerial and the obligatory doily
    b.tube([0.0, 1.0, 0.0], [-0.22, 1.42, -0.05], 0.004, 0.003, 3, A('#9a9a9a', M.CHROME), false);
    b.tube([0.0, 1.0, 0.0], [0.24, 1.4, -0.02], 0.004, 0.003, 3, A('#9a9a9a', M.CHROME), false);
    b.boxMM(-0.2, 1.0, -0.15, 0.2, 1.004, 0.15, A('#e4e0d4', M.LACE));
  },
  radio(b, it) {
    // a 'Gloria' or 'Mamaia' valve radio: veneer, cloth grille, a lit dial
    const a = A(pick(VENEER, it.variant), M.WOOD, { seed: 0.6 });
    b.boxMM(-0.28, 0, -0.14, 0.28, 0.32, 0.14, a);
    b.boxMM(-0.24, 0.06, 0.14, 0.04, 0.28, 0.142, A('#7a6a4a', M.CLOTH, { seed: 0.2 }));
    b.boxMM(0.07, 0.18, 0.14, 0.25, 0.27, 0.143, A('#d8c890', M.LAMP, { aux: [it.on ? 1.5 : 0.05, 0] }));
    for (let i = 0; i < 3; i++) b.tube([0.1 + i * 0.07, 0.09, 0.14], [0.1 + i * 0.07, 0.09, 0.16], 0.016, 0.016, 6, A('#e0d8c0', M.PAINT));
  },
  rug(b, it) {
    const a = A(pick(['#6a1e1a', '#4a2a2a', '#5a3a2a', '#3a2a3a'], it.variant), M.CARPET, { seed: (it.x * 1.3) % 1, aux: [2.4, 1.7] });
    b.push().translate(0, 0.004, 0); b.flat(-1.2, -0.85, 1.2, 0.85, 0, a); b.pop();
  },
  wallcarpet(b, it) {
    // the woven 'carpetă' on the wall above the sofa or bed
    const a = A(pick(['#5a1a16', '#3a2a22', '#6a3a1e', '#2a2a3a'], it.variant), M.CARPET, { seed: (it.z * 2.1) % 1, aux: [2.0, 1.35] });
    b.push().translate(0, 1.35 / 2, 0).box(0, 0, 0, 2.0, 1.35, 0.02, a).pop();
  },
  diningtable(b, it) {
    const a = wood(it, 2);
    b.boxMM(-0.6, 0.71, -0.4, 0.6, 0.75, 0.4, a); legs(b, 1.2, 0.8, 0.71, a, 0.025);
    b.boxMM(-0.65, 0.75, -0.45, 0.65, 0.753, 0.45, A('#e8e4d8', M.LACE, { seed: 0.7 }));
    // a fruit bowl, empty, and a soda siphon
    b.push().translate(0, 0.753, 0).lathe([[0.0, 0], [0.08, 0], [0.13, 0.07], [0.12, 0.08]], 10, A('#9aa8a8', M.CHROME)).pop();
    b.tube([0.35, 0.753, 0.1], [0.35, 0.98, 0.1], 0.045, 0.045, 8, A('#3a5a7a', M.GLASS));
  },
  chair(b, it) {
    const a = wood(it, 2);
    b.boxMM(-0.22, 0.44, -0.22, 0.22, 0.48, 0.22, A(pick(FABRIC, it.variant), M.UPHOLSTERY, { seed: 0.1 }));
    legs(b, 0.44, 0.44, 0.44, a, 0.017, 0.03);
    for (const s of [-1, 1]) b.boxMM(s * 0.2 - 0.017, 0.48, -0.22, s * 0.2 + 0.017, 0.92, -0.19, a);
    b.boxMM(-0.2, 0.7, -0.22, 0.2, 0.88, -0.2, a);
  },
  plant(b, it) {
    // a ficus or a geranium in a glazed pot
    b.lathe([[0.0, 0], [0.11, 0], [0.15, 0.24], [0.14, 0.26], [0.0, 0.25]], 10, A(pick(['#7a3a22', '#4a5a6a', '#d0c8b0'], it.variant), M.PAINT));
    const leaf = A(pick(['#2e4422', '#3a4a26', '#2a3a1e'], it.variant), M.PLAIN, { seed: 0.3 });
    const rnd = rng(it.x * 3.1 + it.z + it.variant);
    for (let i = 0; i < 7; i++) b.push().translate((rnd() - 0.5) * 0.25, 0.4 + rnd() * 0.35, (rnd() - 0.5) * 0.25).blob(0.1 + rnd() * 0.06, leaf, rnd, 1, 0.7, 1, 0.4).pop();
    b.tube([0, 0.25, 0], [0, 0.6, 0], 0.012, 0.008, 4, A('#3a2a1a', M.WOOD), false);
  },
  lamp(b, it, room) {
    // ceiling fittings: a frosted glass bowl, a three-arm chandelier or a fabric shade
    const glow = room.lit ? 2.2 : 0;
    const v = it.variant % 3;
    b.tube([0, -0.0, 0], [0, -0.28, 0], 0.006, 0.006, 4, A('#3a3a3a', M.METAL), false);
    if (v === 0) b.push().translate(0, -0.42, 0).lathe([[0.0, 0], [0.16, 0.02], [0.22, 0.1], [0.2, 0.14]], 12, A('#f0e0c0', M.LAMP, { aux: [glow, 0] })).pop();
    else if (v === 1) {
      for (let i = 0; i < 3; i++) {
        const a = (i / 3) * Math.PI * 2, x = Math.cos(a) * 0.24, z = Math.sin(a) * 0.24;
        b.tube([0, -0.3, 0], [x, -0.36, z], 0.008, 0.008, 4, A('#b09a60', M.CHROME), false);
        b.push().translate(x, -0.36, z).lathe([[0.03, 0], [0.07, 0.02], [0.08, 0.12], [0.0, 0.13]], 8, A('#f0dcb0', M.LAMP, { aux: [glow, 0] })).pop();
      }
    } else b.push().translate(0, -0.52, 0).lathe([[0.24, 0], [0.24, 0.02], [0.12, 0.24], [0.1, 0.24]], 12, A(pick(['#c8a070', '#a07050', '#d0c090'], it.x), M.LAMP, { aux: [glow * 0.6, 0] })).pop();
  },
  bulb(b, _it, room) {
    b.tube([0, 0, 0], [0, -0.14, 0], 0.012, 0.012, 5, A('#2a2a2a', M.PLAIN), false);
    b.push().translate(0, -0.2, 0).lathe([[0.0, -0.03], [0.03, -0.01], [0.032, 0.03], [0.012, 0.06]], 8, A('#fff0d0', M.LAMP, { aux: [room.lit ? 3 : 0, 0] })).pop();
  },
  // ---------------- bedrooms
  bed2(b, it) {
    const a = wood(it, 1), w = 1.55, d = 2.0;
    b.boxMM(-w / 2, 0.1, -d / 2, w / 2, 0.38, d / 2, a);
    b.boxMM(-w / 2, 0.1, -d / 2, w / 2, 1.0, -d / 2 + 0.05, a);
    b.boxMM(-w / 2 + 0.04, 0.38, -d / 2 + 0.05, w / 2 - 0.04, 0.52, d / 2 - 0.04, A('#d8d0c0', M.CLOTH));
    // a quilted bedspread and two square pillows on the diagonal
    b.boxMM(-w / 2 + 0.02, 0.5, -d / 2 + 0.45, w / 2 - 0.02, 0.58, d / 2 - 0.02, A(pick(['#7a2a2a', '#5a4a6a', '#6a5a3a', '#3a4a5a'], it.variant), M.UPHOLSTERY, { seed: 0.2 }));
    for (const s of [-1, 1]) b.push().translate(s * 0.35, 0.62, -d / 2 + 0.28).rotateX(-0.5).box(0, 0, 0, 0.6, 0.6, 0.1, A('#e0dcd0', M.LACE)).pop();
    legs(b, w, d, 0.1, tint(a, 0.7), 0.025);
  },
  bed1(b, it) {
    const a = wood(it, 3), w = 0.92, d = 2.0;
    b.boxMM(-w / 2, 0.1, -d / 2, w / 2, 0.34, d / 2, a);
    b.boxMM(-w / 2, 0.1, -d / 2, w / 2, 0.8, -d / 2 + 0.04, a);
    b.boxMM(-w / 2 + 0.03, 0.34, -d / 2 + 0.04, w / 2 - 0.03, 0.48, d / 2 - 0.03, A('#d0c8b8', M.CLOTH));
    b.boxMM(-w / 2 + 0.01, 0.46, -d / 2 + 0.5, w / 2 - 0.01, 0.53, d / 2 - 0.01, A(pick(['#3a5a7a', '#6a3a3a', '#4a6a4a'], it.variant), M.WOOL, { seed: 0.4 }));
    b.boxMM(-0.3, 0.48, -d / 2 + 0.08, 0.3, 0.6, -d / 2 + 0.42, A('#e8e4d8', M.CLOTH));
    legs(b, w, d, 0.1, tint(a, 0.7), 0.02);
  },
  wardrobe(b, it) {
    const a = wood(it), w = 1.25, d = 0.6, h = 2.0;
    b.boxMM(-w / 2, 0.06, -d / 2, w / 2, h, d / 2, a);
    b.boxMM(-w / 2 + 0.02, 0, -d / 2 + 0.02, w / 2 - 0.02, 0.06, d / 2 - 0.02, tint(a, 0.6));
    b.boxMM(-0.003, 0.1, d / 2, 0.003, h - 0.05, d / 2 + 0.004, tint(a, 0.5));
    for (const s of [-1, 1]) b.box(s * 0.05, 1.1, d / 2 + 0.015, 0.015, 0.12, 0.02, A('#b0a070', M.CHROME));
    // a suitcase on top
    b.boxMM(-0.4, h, -0.22, 0.3, h + 0.18, 0.2, A('#4a3a2a', M.UPHOLSTERY, { seed: 0.8 }));
  },
  dresser(b, it) {
    const a = wood(it, 1);
    b.boxMM(-0.5, 0.05, -0.22, 0.5, 0.8, 0.22, a);
    for (let i = 0; i < 3; i++) { b.boxMM(-0.47, 0.1 + i * 0.23, 0.22, 0.47, 0.3 + i * 0.23, 0.225, tint(a, 1.1)); b.box(0, 0.2 + i * 0.23, 0.235, 0.12, 0.015, 0.015, A('#b0a070', M.CHROME)); }
    b.boxMM(-0.35, 0.8, -0.18, 0.35, 0.803, 0.15, A('#e0dcd0', M.LACE));
  },
  nightstand(b, it) {
    const a = wood(it, 1);
    b.boxMM(-0.22, 0.1, -0.2, 0.22, 0.55, 0.2, a); legs(b, 0.44, 0.4, 0.1, a, 0.015, 0.03);
    // a small lamp and an alarm clock
    b.push().translate(-0.08, 0.55, 0).lathe([[0.05, 0], [0.04, 0.02], [0.01, 0.03], [0.01, 0.2]], 6, A('#8a7a5a', M.CHROME)).pop();
    b.push().translate(-0.08, 0.72, 0).lathe([[0.1, 0], [0.06, 0.12], [0.0, 0.12]], 8, A('#e0c890', M.LAMP, { aux: [0.6, 0] })).pop();
    b.tube([0.1, 0.62, -0.02], [0.1, 0.62, 0.03], 0.05, 0.05, 10, A('#c8b890', M.CHROME));
  },
  desk(b, it) {
    const a = wood(it, 2);
    b.boxMM(-0.55, 0.72, -0.3, 0.55, 0.75, 0.3, a);
    b.boxMM(0.15, 0, -0.28, 0.55, 0.72, 0.28, a);
    legs(b, 1.1, 0.6, 0.72, a, 0.02);
    // exercise books, a pen pot, a desk lamp
    b.boxMM(-0.4, 0.75, -0.05, -0.1, 0.77, 0.15, A('#3a5a8a', M.PAPER));
    b.boxMM(-0.3, 0.77, -0.02, -0.02, 0.775, 0.18, A('#e0dcd0', M.PAPER));
    b.tube([0.35, 0.75, -0.15], [0.35, 1.05, -0.05], 0.01, 0.01, 4, A('#3a5a3a', M.METAL), false);
    b.push().translate(0.35, 1.0, 0.0).lathe([[0.08, 0], [0.05, 0.08], [0.0, 0.1]], 8, A('#4a6a4a', M.METAL)).pop();
  },
  // ---------------- kitchen
  sink(b) {
    b.boxMM(-0.4, 0.05, -0.3, 0.4, 0.85, 0.28, A('#d8d4c8', M.PAINT, { seed: 0.2 }));
    b.boxMM(-0.4, 0.85, -0.3, 0.4, 0.88, 0.3, A('#a0a4a4', M.CHROME));
    b.boxMM(-0.3, 0.7, -0.2, 0.3, 0.875, 0.2, A('#5a5c5c', M.METAL));
    b.tube([0, 0.88, -0.25], [0, 1.08, -0.25], 0.012, 0.012, 5, A('#a0a4a4', M.CHROME), false);
    b.tube([0, 1.08, -0.25], [0, 1.06, -0.08], 0.01, 0.01, 5, A('#a0a4a4', M.CHROME), false);
  },
  stove(b, it) {
    // the white 'Aragaz' with four burners and the gas cylinder's rubber hose
    const e = A(pick(ENAMEL, it.variant), M.PAINT, { seed: 0.4 });
    b.boxMM(-0.28, 0.04, -0.3, 0.28, 0.86, 0.3, e);
    b.boxMM(-0.23, 0.12, 0.3, 0.23, 0.6, 0.305, A('#2a2a2a', M.GLASS));
    for (const [x, z] of [[-0.13, -0.13], [0.13, -0.13], [-0.13, 0.13], [0.13, 0.13]]) b.tube([x, 0.86, z], [x, 0.875, z], 0.07, 0.065, 8, A('#1a1a1a', M.METAL));
    if (it.on) b.tube([-0.13, 0.875, 0.13], [-0.13, 0.885, 0.13], 0.055, 0.04, 8, A('#3060ff', M.LAMP, { aux: [1.6, 0] }));
    for (let i = 0; i < 4; i++) b.tube([-0.18 + i * 0.12, 0.74, 0.3], [-0.18 + i * 0.12, 0.74, 0.33], 0.018, 0.018, 6, A('#2a2a2a', M.PLAIN));
    // an enamel pot with a lid
    b.push().translate(0.13, 0.875, -0.13).lathe([[0.0, 0], [0.1, 0], [0.1, 0.14], [0.11, 0.15], [0.03, 0.17], [0.0, 0.18]], 10, A(pick(['#c84a2a', '#2a5a8a', '#d8d0b8'], it.variant + 1), M.PAINT)).pop();
  },
  cupboard(b, it) {
    const e = A(pick(['#d8d4c8', '#c8d0c0', '#d4c8a8'], it.variant), M.PAINT, { seed: 0.5 });
    b.boxMM(-0.3, 0.05, -0.3, 0.3, 0.86, 0.28, e);
    b.boxMM(-0.3, 0.86, -0.3, 0.3, 0.88, 0.3, A('#8a7a6a', M.PLAIN));
    b.box(0.2, 0.7, 0.29, 0.08, 0.015, 0.015, A('#a0a4a4', M.CHROME));
    // jars of winter preserves (zacuscă, murături) on top
    for (let i = 0; i < 3; i++) b.tube([-0.18 + i * 0.13, 0.88, 0], [-0.18 + i * 0.13, 1.04, 0], 0.045, 0.045, 8, A(pick(['#8a3a1a', '#5a6a2a', '#9a5a1a'], i + it.variant), M.GLASS));
  },
  fridge(b, it) {
    // an 'Arctic' fridge, rounded and humming
    const e = A('#e0dcd0', M.PAINT, { seed: 0.6 });
    b.boxMM(-0.29, 0.04, -0.3, 0.29, 1.45, 0.28, e);
    b.boxMM(-0.27, 0.06, 0.28, 0.27, 1.43, 0.3, tint(e, 1.03));
    b.boxMM(0.2, 0.9, 0.3, 0.23, 1.15, 0.33, A('#a0a4a4', M.CHROME));
    b.boxMM(-0.15, 1.3, 0.3, 0.05, 1.36, 0.305, A('#b02a1a', M.PAINT));
    void it;
  },
  kitchentable(b, it) {
    const a = A('#c8c0a8', M.PAINT, { seed: 0.2 });
    b.boxMM(-0.45, 0.71, -0.33, 0.45, 0.75, 0.33, a); legs(b, 0.9, 0.65, 0.71, A('#8a8a8a', M.CHROME), 0.015);
    // oilcloth with a pattern, a loaf of bread and a bottle of milk
    b.boxMM(-0.5, 0.75, -0.38, 0.5, 0.753, 0.38, A(pick(['#a84a3a', '#4a7a9a', '#7a8a4a'], it.variant), M.CLOTH, { seed: 0.7 }));
    b.push().translate(-0.15, 0.753, 0).scale(1.6, 0.8, 1).blob(0.07, A('#9a6a3a', M.PLAIN), rng(it.x + it.z), 1, 1, 1, 0.15).pop();
    b.tube([0.2, 0.753, 0.05], [0.2, 0.95, 0.05], 0.035, 0.03, 8, A('#e8e8e0', M.GLASS));
  },
  stool(b) {
    const a = A('#8a6a44', M.WOOD, { seed: 0.3 });
    b.boxMM(-0.17, 0.42, -0.17, 0.17, 0.46, 0.17, a); legs(b, 0.34, 0.34, 0.42, a, 0.015, 0.03);
  },
  shelf(b, it) {
    const a = wood(it, 2);
    b.boxMM(-0.45, 0, -0.12, 0.45, 0.02, 0.12, a);
    for (let i = 0; i < 4; i++) b.push().translate(-0.32 + i * 0.2, 0.02, 0).lathe([[0.0, 0], [0.05, 0], [0.05, 0.12], [0.03, 0.14], [0.0, 0.14]], 8, A(pick(['#c8b890', '#d8d4c8', '#8a3a2a'], i), M.PAINT)).pop();
  },
  speaker(b, it) {
    // the wired radio-diffusion speaker ('difuzor') every flat had
    b.boxMM(-0.15, 0, -0.06, 0.15, 0.26, 0.06, A('#5a4632', M.WOOD, { seed: 0.4 }));
    b.boxMM(-0.11, 0.05, 0.06, 0.11, 0.22, 0.062, A('#8a7a5a', M.CLOTH));
    void it;
  },
  // ---------------- bathroom
  tub(b) {
    const e = A('#e4e0d4', M.PAINT, { seed: 0.3 });
    b.boxMM(-0.78, 0, -0.36, 0.78, 0.56, 0.36, e, { py: false });
    b.boxMM(-0.7, 0.2, -0.29, 0.7, 0.55, 0.29, A('#c8c8c0', M.PAINT), { py: false, ny: false });
    for (const [x0, x1, z0, z1] of [[-0.78, 0.78, -0.36, -0.29], [-0.78, 0.78, 0.29, 0.36], [-0.78, -0.7, -0.29, 0.29], [0.7, 0.78, -0.29, 0.29]]) b.flat(x0, z0, x1, z1, 0.56, e);
    b.tube([0.7, 0.56, -0.33], [0.7, 0.9, -0.36], 0.012, 0.012, 5, A('#a0a4a4', M.CHROME), false);
    // the washing board and a tin bowl, for laundry
    b.push().translate(-0.3, 0.56, 0).rotateZ(0.1).box(0, 0.02, 0, 0.5, 0.03, 0.3, A('#8a7a5a', M.WOOD)).pop();
  },
  basin(b) {
    const e = A('#e4e0d4', M.PAINT, { seed: 0.3 });
    b.tube([0, 0, -0.1], [0, 0.72, -0.12], 0.08, 0.06, 8, e);
    b.boxMM(-0.26, 0.72, -0.21, 0.26, 0.86, 0.21, e);
    b.boxMM(-0.2, 0.8, -0.15, 0.2, 0.861, 0.17, A('#9a9a94', M.CHROME));
    b.tube([0, 0.86, -0.18], [0, 0.98, -0.12], 0.01, 0.01, 5, A('#a0a4a4', M.CHROME), false);
  },
  toilet(b) {
    const e = A('#e4e0d4', M.PAINT, { seed: 0.3 });
    b.push().translate(0, 0, 0.05).lathe([[0.12, 0], [0.14, 0.2], [0.2, 0.38], [0.2, 0.4]], 10, e, 1, 1.35).pop();
    b.boxMM(-0.19, 0.4, -0.2, 0.19, 0.43, 0.32, A('#2a2a2a', M.PLAIN));
    // high cistern with a pull chain
    b.boxMM(-0.22, 1.7, -0.33, 0.22, 1.95, -0.16, A('#d8d4c8', M.PAINT));
    b.tube([0, 1.7, -0.28], [0, 0.42, -0.28], 0.02, 0.02, 6, A('#a0a4a4', M.CHROME), false);
    b.tube([0.15, 1.7, -0.2], [0.15, 1.1, -0.2], 0.003, 0.003, 3, A('#a0a4a4', M.CHROME), false);
  },
  mirror(b) {
    b.boxMM(-0.25, 0, -0.015, 0.25, 0.65, 0.0, A('#8a8a82', M.PAINT));
    b.boxMM(-0.22, 0.03, 0.0, 0.22, 0.62, 0.005, A('#a0a8a8', M.CHROME));
    b.boxMM(-0.25, -0.05, 0, 0.25, -0.03, 0.12, A('#d8d8d0', M.GLASS));
  },
  // ---------------- hall
  coatrack(b, it) {
    const a = wood(it, 1);
    b.boxMM(-0.45, 1.55, -0.16, 0.45, 1.6, 0.16, a);
    b.boxMM(-0.45, 1.3, -0.16, 0.45, 1.55, -0.13, a);
    for (let i = 0; i < 4; i++) b.tube([-0.33 + i * 0.22, 1.42, -0.13], [-0.33 + i * 0.22, 1.45, 0.0], 0.012, 0.012, 4, A('#b0a070', M.CHROME), false);
    // winter coats and a fur hat
    const coats = ['#3a3a3a', '#4a3a2a', '#2a3040', '#5a4a3a'];
    for (let i = 0; i < 3; i++) b.boxMM(-0.38 + i * 0.25, 0.55, -0.1, -0.2 + i * 0.25, 1.42, 0.08, A(coats[(i + it.variant) % 4], M.WOOL, { seed: i / 3 }));
    b.push().translate(0.25, 1.6, 0).lathe([[0.1, 0], [0.11, 0.12], [0.0, 0.13]], 10, A('#2a2420', M.WOOL)).pop();
  },
  shoecabinet(b, it) {
    const a = wood(it, 2);
    b.boxMM(-0.4, 0.05, -0.17, 0.4, 0.88, 0.17, a);
    b.boxMM(-0.38, 0.1, 0.17, 0.38, 0.84, 0.172, tint(a, 1.1));
    // slippers left out on the floor
    for (const s of [-1, 1]) b.boxMM(s * 0.08 - 0.05, 0, 0.22, s * 0.08 + 0.05, 0.04, 0.48, A('#5a3a3a', M.WOOL));
  },
  phonetable(b, it) {
    const a = wood(it, 2);
    b.boxMM(-0.25, 0.7, -0.2, 0.25, 0.74, 0.2, a); legs(b, 0.5, 0.4, 0.7, a, 0.015);
    // the rotary telephone, the phone book
    b.boxMM(-0.12, 0.74, -0.1, 0.12, 0.84, 0.1, A(pick(['#2a2a2a', '#d8c8a0', '#6a1a1a'], it.variant), M.PAINT));
    b.tube([0, 0.84, 0.06], [0, 0.85, 0.06], 0.06, 0.06, 10, A('#e0dcd0', M.PAINT));
    b.boxMM(-0.13, 0.84, -0.09, 0.13, 0.88, -0.03, A(pick(['#2a2a2a', '#d8c8a0', '#6a1a1a'], it.variant), M.PAINT));
    b.boxMM(0.0, 0.74, 0.1, 0.18, 0.77, 0.19, A('#c8b890', M.PAPER));
  },
  // ---------------- storage, shops, schools, workshops
  shelves(b, it) {
    const a = A(pick(['#6a6a62', '#5a4a32'], it.variant), it.variant % 2 ? M.WOOD : M.METAL, { seed: 0.5 });
    for (const s of [-1, 1]) b.boxMM(s * 0.6 - 0.02, 0, -0.21, s * 0.6 + 0.02, 2.0, 0.21, a);
    for (let i = 0; i < 5; i++) b.boxMM(-0.6, 0.1 + i * 0.45, -0.21, 0.6, 0.13 + i * 0.45, 0.21, a);
    // jars, boxes and old newspapers
    for (let i = 0; i < 4; i++) for (let k = 0; k < 4; k++) if ((i * 7 + k * 3 + it.variant) % 3) b.boxMM(-0.55 + k * 0.28, 0.13 + i * 0.45, -0.15, -0.35 + k * 0.28, 0.33 + i * 0.45, 0.15, A(pick(['#8a7a5a', '#6a5a4a', '#9a8a6a', '#7a3a2a'], i + k), M.PAPER));
  },
  crate(b) {
    const a = A('#8a7a5a', M.WOOD, { seed: 0.7 });
    b.boxMM(-0.3, 0, -0.21, 0.3, 0.32, 0.21, a);
    // potatoes or empty bottles
    b.boxMM(-0.28, 0.25, -0.19, 0.28, 0.3, 0.19, A('#7a6a4a', M.GRAVEL));
  },
  shopcounter(b) {
    const a = A('#6a5a4a', M.WOOD, { seed: 0.3 });
    b.boxMM(-1.2, 0, -0.35, 1.2, 0.92, 0.35, a);
    b.boxMM(-1.25, 0.92, -0.38, 1.25, 0.95, 0.38, A('#8a8478', M.TERRAZZO));
    b.boxMM(-1.15, 0.3, 0.35, 1.15, 0.85, 0.36, A('#000000', M.GLASS));
  },
  shopshelf(b, it) {
    const a = A('#7a6a52', M.WOOD, { seed: 0.4 });
    b.boxMM(-0.9, 0, -0.23, 0.9, 2.2, -0.2, a);
    for (const s of [-1, 1]) b.boxMM(s * 0.9 - 0.02, 0, -0.23, s * 0.9 + 0.02, 2.2, 0.23, a);
    for (let i = 0; i < 5; i++) b.boxMM(-0.9, 0.2 + i * 0.45, -0.23, 0.9, 0.23 + i * 0.45, 0.23, a);
    // the famous near-empty shelves: one product, stacked into pyramids
    const prod = pick(['#8a6a2a', '#5a7a3a', '#9a3a2a', '#c8b890'], it.variant);
    for (let i = 0; i < 5; i++) if ((i + it.variant) % 2 === 0) for (let k = 0; k < 5; k++) b.tube([-0.6 + k * 0.3, 0.23 + i * 0.45, 0.05], [-0.6 + k * 0.3, 0.35 + i * 0.45, 0.05], 0.04, 0.04, 8, A(prod, M.PAINT, { seed: 0.2 }));
  },
  scale(b) {
    b.boxMM(-0.18, 0, -0.12, 0.18, 0.08, 0.12, A('#d8d4c8', M.PAINT));
    b.tube([0, 0.08, -0.05], [0, 0.32, -0.05], 0.015, 0.015, 6, A('#d8d4c8', M.PAINT));
    b.tube([0, 0.32, -0.08], [0, 0.32, 0.0], 0.09, 0.09, 12, A('#e0dcd0', M.PAINT));
    b.flat(-0.15, -0.1, 0.15, 0.1, 0.1, A('#a0a4a4', M.CHROME));
  },
  schooldesk(b) {
    const a = A('#6a5a3a', M.WOOD, { seed: 0.4 });
    b.push().translate(0, 0.72, 0).rotateX(0.12).box(0, 0, 0, 1.1, 0.03, 0.5, a).pop();
    b.boxMM(-0.55, 0.0, -0.25, -0.5, 0.72, 0.25, A('#3a4a3a', M.METAL)); b.boxMM(0.5, 0.0, -0.25, 0.55, 0.72, 0.25, A('#3a4a3a', M.METAL));
    b.boxMM(-0.52, 0.55, -0.22, 0.52, 0.57, 0.22, a);
    // the bench seat, joined to the desk
    b.boxMM(-0.52, 0.42, 0.45, 0.52, 0.45, 0.75, a);
  },
  teacherdesk(b) {
    const a = A('#5a4a32', M.WOOD, { seed: 0.3 });
    b.boxMM(-0.62, 0.72, -0.31, 0.62, 0.76, 0.31, a);
    b.boxMM(-0.62, 0, -0.3, -0.2, 0.72, 0.3, a); b.boxMM(0.2, 0, -0.3, 0.62, 0.72, 0.3, a);
    b.boxMM(-0.4, 0.76, -0.1, -0.1, 0.8, 0.15, A('#2a3a5a', M.PAPER));
  },
  blackboard(b) {
    b.boxMM(-1.4, 0, -0.025, 1.4, 1.2, 0.0, A('#5a4a32', M.WOOD));
    b.boxMM(-1.35, 0.05, 0.0, 1.35, 1.15, 0.005, A('#1e2a22', M.SCREEN, { aux: [0, 0] }));
    b.boxMM(-1.4, -0.04, 0.0, 1.4, -0.0, 0.08, A('#5a4a32', M.WOOD));
  },
  portraitshadow(b) {
    // where the Comrade's portrait hung until this morning: a pale patch and a nail
    b.boxMM(-0.31, 0, 0.0, 0.31, 0.82, 0.002, A('#ffffff', M.DECAL, { seed: 0.5, aux: [1, 0] }));
    b.tube([0, 0.86, 0], [0, 0.86, 0.03], 0.004, 0.004, 3, A('#4a4a4a', M.METAL), false);
  },
  filing(b) {
    const a = A('#6a6e62', M.METAL, { seed: 0.4 });
    b.boxMM(-0.25, 0, -0.3, 0.25, 1.3, 0.3, a);
    for (let i = 0; i < 4; i++) b.box(0, 0.2 + i * 0.3, 0.31, 0.12, 0.02, 0.02, A('#a0a4a4', M.CHROME));
  },
  lathe(b) {
    const a = A('#4a5a52', M.METAL, { seed: 0.5 });
    b.boxMM(-0.95, 0, -0.3, -0.55, 0.85, 0.3, a); b.boxMM(0.55, 0, -0.3, 0.95, 0.85, 0.3, a);
    b.boxMM(-0.95, 0.85, -0.35, 0.95, 0.95, 0.35, a);
    b.boxMM(-0.9, 0.95, -0.25, -0.45, 1.25, 0.25, a);
    b.tube([-0.45, 1.1, 0], [0.7, 1.1, 0], 0.03, 0.03, 8, A('#8a8a8a', M.CHROME));
  },
  workbench(b) {
    const a = A('#6a5232', M.WOOD, { seed: 0.4 });
    b.boxMM(-1.0, 0.84, -0.4, 1.0, 0.9, 0.4, a); legs(b, 2.0, 0.8, 0.84, a, 0.04);
    b.boxMM(0.7, 0.9, -0.1, 0.95, 1.05, 0.2, A('#3a4a5a', M.METAL));
    for (let i = 0; i < 5; i++) b.boxMM(-0.8 + i * 0.12, 0.9, -0.3, -0.75 + i * 0.12, 0.92, 0.1, A('#5a5a5a', M.METAL));
  },
  barrel(b) {
    b.lathe([[0.26, 0], [0.3, 0.45], [0.26, 0.9], [0.0, 0.9]], 10, A('#5a6a5a', M.METAL, { seed: 0.3 }));
  },
  iconostasis(b) {
    const a = A('#5a3a1e', M.WOOD, { seed: 0.3 });
    b.boxMM(-2, 0, -0.15, 2, 3.4, 0.15, a);
    for (let i = 0; i < 5; i++) for (let k = 0; k < 2; k++) b.boxMM(-1.8 + i * 0.75, 0.9 + k * 1.2, 0.15, -1.25 + i * 0.75, 1.8 + k * 1.2, 0.16, A(k ? '#9a7a3a' : '#7a5a2a', M.CHROME));
    b.boxMM(-0.45, 0, 0.15, 0.45, 2.2, 0.17, A('#9a7a3a', M.CHROME));
  },
  candlestand(b, _it, room) {
    b.lathe([[0.2, 0], [0.05, 0.05], [0.04, 0.9], [0.25, 0.95], [0.25, 1.0]], 10, A('#9a7a3a', M.CHROME));
    for (let i = 0; i < 6; i++) { const a = (i / 6) * Math.PI * 2; b.tube([Math.cos(a) * 0.16, 1.0, Math.sin(a) * 0.16], [Math.cos(a) * 0.16, 1.18, Math.sin(a) * 0.16], 0.008, 0.008, 4, A('#e8d8a0', M.PAINT)); b.push().translate(Math.cos(a) * 0.16, 1.2, Math.sin(a) * 0.16).blob(0.012, A('#ffb050', M.LAMP, { aux: [6, 0] }), rng(i), 1, 1.8, 1, 0).pop(); }
    void room;
  },
  bench(b) {
    const a = A('#6a5232', M.WOOD, { seed: 0.4 });
    b.boxMM(-0.95, 0.42, -0.22, 0.95, 0.46, 0.22, a); legs(b, 1.9, 0.44, 0.42, a, 0.03);
  },
  car(b, it) {
    // a Dacia 1300 under a tarpaulin in the garage
    const p = A(pick(['#4a5244', '#5a5a4e', '#3a4048'], it.variant), M.CLOTH, { seed: 0.3 });
    b.boxMM(-0.8, 0.25, -2.15, 0.8, 0.95, 2.15, p);
    b.push().translate(0, 0.95, -0.3).scale(1, 0.5, 1.6).box(0, 0.5, 0, 1.5, 1.0, 1.2, p).pop();
    for (const sx of [-0.7, 0.7]) for (const sz of [-1.25, 1.25]) b.tube([sx - 0.1, 0.3, sz], [sx + 0.1, 0.3, sz], 0.3, 0.3, 10, A('#141414', M.RUBBER));
  },
  tyres(b) {
    for (let i = 0; i < 4; i++) b.tube([0, i * 0.2, 0], [0, i * 0.2 + 0.19, 0], 0.31, 0.31, 12, A('#151515', M.RUBBER));
  },
  mailboxes(b) {
    const a = A('#5a6a5a', M.METAL, { seed: 0.4 });
    b.boxMM(-0.65, 0, -0.08, 0.65, 0.75, 0.08, a);
    for (let i = 0; i < 5; i++) for (let k = 0; k < 3; k++) b.boxMM(-0.6 + i * 0.25, 0.05 + k * 0.24, 0.08, -0.38 + i * 0.25, 0.25 + k * 0.24, 0.085, tint(a, 1.1));
  },
  radiator(b, it) {
    // cast-iron 'calorifer', painted over many times
    const n = 6 + (it.variant || 2) * 3;
    const w = 0.9 * Math.max(1, it.variant || 1) / 1.5;
    for (let i = 0; i < n; i++) { const x = -w / 2 + (i + 0.5) * (w / n); b.boxMM(x - (w / n) * 0.4, 0, -0.05, x + (w / n) * 0.4, 0.55, 0.05, A('#c8c4b4', M.PAINT, { seed: 0.3 })); }
  },
  curtain(b, it) {
    // heavy drapes either side and the lace net in the middle
    const w = it.w ?? 1.6, h = it.h ?? 2.2;
    const drape = A(pick(['#5a1e1a', '#6a5a2a', '#3a4a3a', '#4a3a4a'], it.variant), M.UPHOLSTERY, { seed: 0.4 });
    b.boxMM(-w / 2 - 0.2, h, -0.03, w / 2 + 0.2, h + 0.04, 0.0, A('#5a4a32', M.WOOD));
    b.boxMM(-w / 2 - 0.15, 0, -0.02, -w / 2 + 0.2, h, 0.02, drape);
    b.boxMM(w / 2 - 0.2, 0, -0.02, w / 2 + 0.15, h, 0.02, drape);
    b.boxMM(-w / 2 + 0.2, 0.15, 0.02, w / 2 - 0.2, h, 0.025, A('#e4e0d4', M.LACE, { seed: 0.5 }));
  },
  calendar(b) {
    b.boxMM(-0.15, 0, 0.0, 0.15, 0.42, 0.006, A('#e0dcd0', M.PAPER));
    b.boxMM(-0.13, 0.22, 0.006, 0.13, 0.4, 0.007, A('#7a3a2a', M.PAPER));
  },
  picture(b, it) {
    b.boxMM(-0.25, 0, 0, 0.25, 0.4, 0.02, A('#6a4a22', M.WOOD));
    b.boxMM(-0.21, 0.04, 0.02, 0.21, 0.36, 0.022, A(pick(['#4a5a3a', '#6a5a4a', '#3a4a5a'], it.variant), M.PAINT));
  },
  doorplate(b) {
    b.boxMM(-0.07, 0, 0, 0.07, 0.06, 0.006, A('#b0a070', M.CHROME));
  },
  ironingboard(b) {
    b.boxMM(-0.6, 0.82, -0.17, 0.6, 0.85, 0.17, A('#c8c0a0', M.CLOTH));
    b.tube([-0.4, 0, -0.15], [0.3, 0.82, 0], 0.012, 0.012, 4, A('#8a8a8a', M.CHROME), false);
    b.tube([0.3, 0, -0.15], [-0.4, 0.82, 0], 0.012, 0.012, 4, A('#8a8a8a', M.CHROME), false);
    b.boxMM(0.3, 0.85, -0.06, 0.5, 0.95, 0.06, A('#9a9a9a', M.CHROME));
  },
  sewingmachine(b) {
    // a treadle 'Singer' copy: cast-iron stand, wooden top, black head
    b.boxMM(-0.3, 0.72, -0.22, 0.3, 0.76, 0.22, A('#5a3a22', M.WOOD));
    for (const s of [-1, 1]) b.boxMM(s * 0.27 - 0.02, 0, -0.18, s * 0.27 + 0.02, 0.72, 0.18, A('#2a2a2a', M.METAL));
    b.boxMM(-0.2, 0.76, -0.06, 0.18, 0.84, 0.06, A('#1a1a1a', M.PAINT));
    b.boxMM(-0.2, 0.84, -0.05, -0.1, 1.02, 0.05, A('#1a1a1a', M.PAINT));
    b.boxMM(-0.2, 0.96, -0.04, 0.18, 1.04, 0.04, A('#1a1a1a', M.PAINT));
  },
};

/** Draw one placed item into the builder. */
export function drawItem(b: GeoBuilder, it: FurnitureItem, room: Room, g: GeoBuilder | null) {
  const f = MODELS[it.type];
  if (!f) return;
  b.push().translate(it.x, it.y, it.z).rotateY(it.rot);
  f(b, it, room, g);
  b.pop();
}
export const FURNITURE_MODELS = Object.keys(MODELS);
export type { V3 };
