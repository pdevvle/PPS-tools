// Deterministic randomness. Every generated thing is seeded from stable ids,
// so the same building always gets the same rooms, furniture and family.

export type Rng = () => number;

export function mulberry32(seed: number): Rng {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a hash of a string, for turning ids into seeds. */
export function hashStr(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function rngFor(...parts: (string | number)[]): Rng {
  return mulberry32(hashStr(parts.join('|')));
}

export const pick = <T>(r: Rng, xs: readonly T[]): T => xs[Math.floor(r() * xs.length) % xs.length];
export const range = (r: Rng, a: number, b: number): number => a + (b - a) * r();
export const chance = (r: Rng, p: number): boolean => r() < p;

/** Pick by weight: entries are [value, weight]. */
export function weighted<T>(r: Rng, entries: readonly (readonly [T, number])[]): T {
  let total = 0;
  for (const [, w] of entries) total += w;
  let x = r() * total;
  for (const [v, w] of entries) {
    x -= w;
    if (x <= 0) return v;
  }
  return entries[entries.length - 1][0];
}
