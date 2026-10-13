// ===================================================================
// Surface codes for the world shader (per-vertex aMat) and colour helpers.
// Pure data: shared by the main thread, the mesh worker and any port.
// ===================================================================
export const M = {
  PLAIN: 0, PANEL: 1, WIN: 2, PLASTER: 3, BRICK: 4, ASPHALT: 5, COBBLE: 6, SIDEWALK: 7, VERGE: 8,
  METAL: 9, WOOD: 10, TILE: 11, ROOFFLAT: 12, SHOP: 13, SIGN: 14, DECAL: 15, PAINT: 16, GLASS: 17,
  CHROME: 18, RUBBER: 19, BARK: 20, SNOW: 21, WALLPAPER: 22, RAIL: 23, GRAVEL: 24, FAR: 25, FLAG: 26,
  CLOTH: 27, CONCRETE: 28, MOSAIC: 29, WOOL: 30, PAPER: 37, LAMP: 44, TINROOF: 45, BANNER: 46,
  // interiors
  PARQUET: 48, FLOORTILE: 49, TERRAZZO: 50, WALLTILE: 51, OILPAINT: 52, CARPET: 53, SCREEN: 54, LINO: 55,
  UPHOLSTERY: 56, LACE: 57,
} as const;

const s2l = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const cache = new Map<string, [number, number, number]>();
/** '#rrggbb' (display sRGB) → linear rgb triple. */
export function lin(hex: string): [number, number, number] {
  let v = cache.get(hex);
  if (!v) {
    const n = parseInt(hex.slice(1), 16);
    v = [s2l(((n >> 16) & 255) / 255), s2l(((n >> 8) & 255) / 255), s2l((n & 255) / 255)];
    cache.set(hex, v);
  }
  return v;
}
