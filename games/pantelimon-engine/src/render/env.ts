// ===================================================================
// Sun and moon over Bucharest, 21–26 December 1989; a palette keyed by
// solar elevation; weather tied to the real days of that week.
// ===================================================================
import * as THREE from 'three';
import { U } from './uniforms';

const clamp = (x: number, a: number, b: number) => (x < a ? a : x > b ? b : x);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const smoothstep = (a: number, b: number, x: number) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const s2l = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const lin = (hex: string) => { const c = new THREE.Color(hex); return new THREE.Vector3(s2l(c.r), s2l(c.g), s2l(c.b)); };
const TAU = Math.PI * 2;
const LAT = (44.43 * Math.PI) / 180;

function celestial(hours: number, declDeg: number, noon: number, out: THREE.Vector3): number {
  const decl = (declDeg * Math.PI) / 180;
  const H = ((hours - noon) * 15 * Math.PI) / 180;
  const el = Math.asin(clamp(Math.sin(LAT) * Math.sin(decl) + Math.cos(LAT) * Math.cos(decl) * Math.cos(H), -1, 1));
  let az = Math.acos(clamp((Math.sin(decl) - Math.sin(el) * Math.sin(LAT)) / Math.max(1e-5, Math.cos(el) * Math.cos(LAT)), -1, 1));
  if (Math.sin(H) > 0) az = TAU - az;
  // x east, z south, y up
  out.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
  return (el * 180) / Math.PI;
}

const PALETTE_SRC = [
  { e: -18, zen: '#06090f', hor: '#191b22', glow: '#000000', light: '#8090b8', li: 0.0, ambS: '#1b2131', ambG: '#131418', cl: '#1b1e26', cs: '#0c0d12', exp: 2.5 },
  { e: -9, zen: '#111a2e', hor: '#3a3b4a', glow: '#3a2a36', light: '#8090b8', li: 0.0, ambS: '#2b3350', ambG: '#202128', cl: '#3a3846', cs: '#1a1c26', exp: 2.3 },
  { e: -4, zen: '#20304f', hor: '#76606a', glow: '#94503e', light: '#ff7a3a', li: 0.0, ambS: '#454d68', ambG: '#312e35', cl: '#86606a', cs: '#323246', exp: 1.85 },
  { e: -1, zen: '#2a3d68', hor: '#b67c66', glow: '#d86a3c', light: '#ff7a3a', li: 0.0, ambS: '#59617e', ambG: '#423d44', cl: '#c88066', cs: '#4a485c', exp: 1.55 },
  { e: 2, zen: '#38507c', hor: '#d29676', glow: '#f2844a', light: '#ff9050', li: 0.6, ambS: '#6a7392', ambG: '#524c54', cl: '#e6a07c', cs: '#5e5a72', exp: 1.32 },
  { e: 6, zen: '#46638e', hor: '#d8ae8e', glow: '#f4a264', light: '#ffac6a', li: 0.98, ambS: '#78829e', ambG: '#5e5860', cl: '#eebe9c', cs: '#6e6c88', exp: 1.18 },
  { e: 12, zen: '#5072a0', hor: '#d0bca8', glow: '#eec290', light: '#ffc690', li: 1.22, ambS: '#8691ac', ambG: '#6a666c', cl: '#eed8c4', cs: '#7e8296', exp: 1.08 },
  { e: 23, zen: '#577aa8', hor: '#c8c2b8', glow: '#e2d0b4', light: '#ffdcb6', li: 1.36, ambS: '#909bb2', ambG: '#74727a', cl: '#f2e8dc', cs: '#8a8ea0', exp: 1.02 },
];
const KEYS = ['zen', 'hor', 'glow', 'light', 'ambS', 'ambG', 'cl', 'cs'] as const;
type Key = (typeof KEYS)[number];
const PALETTE = PALETTE_SRC.map((k) => ({ e: k.e, li: k.li, exp: k.exp, ...Object.fromEntries(KEYS.map((n) => [n, lin(k[n])])) })) as unknown as ({ e: number; li: number; exp: number } & Record<Key, THREE.Vector3>)[];
const pal = { li: 0, exp: 1, ...Object.fromEntries(KEYS.map((n) => [n, new THREE.Vector3()])) } as { li: number; exp: number } & Record<Key, THREE.Vector3>;
function samplePalette(e: number) {
  let i = 0;
  while (i < PALETTE.length - 2 && e > PALETTE[i + 1].e) i++;
  const a = PALETTE[i], b = PALETTE[i + 1];
  const t = clamp((e - a.e) / (b.e - a.e), 0, 1);
  for (const k of KEYS) pal[k].copy(a[k]).lerp(b[k], t);
  pal.li = lerp(a.li, b.li, t); pal.exp = lerp(a.exp, b.exp, t);
}
function greyMix(v: THREE.Vector3, k: number) {
  const l = v.x * 0.2126 + v.y * 0.7152 + v.z * 0.0722;
  v.x = lerp(v.x, l * 0.96, k); v.y = lerp(v.y, l, k); v.z = lerp(v.z, l * 1.06, k);
}

export const WEATHER = {
  clear: { label: 'Hazy (22 Dec)', cloud: 0.3, fog: 0.0022, falloff: 0.035, haze: 0.0024, wet: 0.08, snow: 0, wind: 0.12, cover: 0, smog: 0.35 },
  overcast: { label: 'Overcast', cloud: 0.92, fog: 0.003, falloff: 0.03, haze: 0.0032, wet: 0.4, snow: 0, wind: 0.22, cover: 0, smog: 0.2 },
  fog: { label: 'Fog (21 Dec)', cloud: 0.8, fog: 0.028, falloff: 0.06, haze: 0.009, wet: 0.75, snow: 0, wind: 0.03, cover: 0, smog: 0.5 },
  snow: { label: 'First snow (26 Dec)', cloud: 1.0, fog: 0.004, falloff: 0.02, haze: 0.0055, wet: 0.5, snow: 0.6, wind: 0.38, cover: 1, smog: 0 },
};
export type WeatherKey = keyof typeof WEATHER;

export class Environment {
  wx = { ...WEATHER.clear };
  sunDir = new THREE.Vector3();
  moonDir = new THREE.Vector3();
  sunElev = 0; night = 0; winLit = 0; snowCover = 0; smog = 0;
  constructor(private skyMat: THREE.ShaderMaterial) {}
  update(hours: number, dt: number, target: WeatherKey) {
    const tw = WEATHER[target], wx = this.wx;
    const k = Math.min(1, dt * 0.35);
    for (const key of ['cloud', 'fog', 'falloff', 'haze', 'wet', 'snow', 'wind', 'smog'] as const) wx[key] = lerp(wx[key], tw[key], k);
    this.snowCover = clamp(this.snowCover + (tw.cover > 0 ? (dt / 70) * (wx.snow / 0.6) : -dt / 40), 0, 1);
    const e = celestial(hours, -23.44, 12.23, this.sunDir);
    const me = celestial(hours + 4.4, -14, 12.23, this.moonDir);
    this.sunElev = e;
    samplePalette(e);
    const c = wx.cloud;
    pal.zen.lerp(pal.hor, c * 0.55); greyMix(pal.zen, c * 0.85);
    greyMix(pal.hor, c * 0.7);
    pal.glow.multiplyScalar(1 - c * 0.8);
    greyMix(pal.ambS, c * 0.45); pal.ambS.multiplyScalar(1 + c * 0.3);
    greyMix(pal.cl, c * 0.6); pal.cl.lerp(pal.hor, c * 0.45);
    greyMix(pal.cs, c * 0.5);
    const sm = wx.smog;
    pal.hor.x *= 1 + sm * 0.08; pal.hor.z *= 1 - sm * 0.12;
    pal.light.y *= 1 - sm * 0.08; pal.light.z *= 1 - sm * 0.22;
    const moonI = smoothstep(-2, 8, me) * smoothstep(-6, -12, e) * 0.08;
    const sunI = pal.li * (1 - c * 0.82);
    if (e > -3) { U.uLightDir.value.copy(this.sunDir); U.uLightCol.value.copy(pal.light).multiplyScalar(sunI); }
    else { U.uLightDir.value.copy(this.moonDir); U.uLightCol.value.set(0.55, 0.65, 0.9).multiplyScalar(moonI * (1 - c * 0.85)); }
    U.uSunDir.value.copy(this.sunDir); U.uMoonDir.value.copy(this.moonDir);
    U.uZenith.value.copy(pal.zen); U.uHorizon.value.copy(pal.hor); U.uGlow.value.copy(pal.glow);
    U.uAmbSky.value.copy(pal.ambS); U.uAmbGround.value.copy(pal.ambG);
    U.uCloudLit.value.copy(pal.cl); U.uCloudShade.value.copy(pal.cs);
    U.uCloudiness.value = c;
    U.uSunDisc.value.copy(pal.light).multiplyScalar(e > -1 ? 7 * (1 - c * 0.92) * smoothstep(-1, 1, e) : 0);
    U.uStars.value = smoothstep(-7, -14, e);
    this.skyMat.uniforms.uMoonVis.value = smoothstep(-1, 2, me) * (0.35 + 0.65 * smoothstep(-2, -10, e)) * (1 - c * 0.9);
    U.uFogDensity.value = wx.fog; U.uFogFalloff.value = wx.falloff; U.uHaze.value = wx.haze;
    U.uExposure.value = pal.exp * (1 + c * 0.12);
    U.uWet.value = wx.wet;
    U.uSnowCover.value = this.snowCover;
    U.uWind.value = wx.wind;
    U.uShadowStrength.value = clamp(1 - c * 0.92, 0, 1) * smoothstep(-3, 1, e > -3 ? e : me);
    this.night = smoothstep(-2, -10, e);
    const late = smoothstep(22, 24, hours) + (hours < 6 ? 1 : 0);
    this.winLit = smoothstep(2, -5, e) * (1 - 0.6 * clamp(late, 0, 1)) + c * 0.2 * smoothstep(8, 2, e);
    U.uWinLit.value = this.winLit;
    U.uNight.value = this.night;
    this.smog = sm;
  }
}
