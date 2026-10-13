// ===================================================================
// Shared uniforms and GLSL helpers used by every shader in the engine:
// noise, sky gradient, height fog, the sun's shadow map, local lights,
// lighting and the ACES tonemap.
// ===================================================================
import * as THREE from 'three';

const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
export const U = {
  uTime: { value: 0 },
  uCamPos: { value: V3() },
  uSunDir: { value: V3(0, 1, 0) },
  uMoonDir: { value: V3(0, -1, 0) },
  uLightDir: { value: V3(0, 1, 0) },
  uLightCol: { value: V3(1, 1, 1) },
  uAmbSky: { value: V3(0.3, 0.35, 0.45) },
  uAmbGround: { value: V3(0.2, 0.2, 0.2) },
  uZenith: { value: V3(0.1, 0.2, 0.5) },
  uHorizon: { value: V3(0.6, 0.6, 0.6) },
  uGlow: { value: V3() },
  uCloudLit: { value: V3(1, 1, 1) },
  uCloudShade: { value: V3(0.5, 0.5, 0.5) },
  uCloudiness: { value: 0.2 },
  uCloudOffset: { value: new THREE.Vector2() },
  uSunDisc: { value: V3() },
  uStars: { value: 0 },
  uFogDensity: { value: 0.002 },
  uFogFalloff: { value: 0.02 },
  uHaze: { value: 0.001 },
  uExposure: { value: 1 },
  uSnowCover: { value: 0 },
  uWet: { value: 0.3 },
  uWindDir: { value: new THREE.Vector2(0.8, 0.6) },
  uWind: { value: 0.15 },
  uNight: { value: 0 },
  uWinLit: { value: 0 },
  uShadowMap: { value: null as THREE.Texture | null },
  uShadowMatrix: { value: new THREE.Matrix4() },
  uShadowStrength: { value: 1 },
  uShadowTexel: { value: 1 / 2048 },
  uPL: { value: Array.from({ length: 8 }, () => new THREE.Vector4(0, 0, 0, 0)) },
  uPLC: { value: Array.from({ length: 8 }, () => V3()) },
  uHide: { value: null as THREE.Texture | null },
};
export type Uniforms = typeof U;

export const GLSL_COMMON = /* glsl */`
uniform float uTime;
uniform vec3 uCamPos;
uniform vec3 uSunDir;
uniform vec3 uMoonDir;
uniform vec3 uLightDir;
uniform vec3 uLightCol;
uniform vec3 uAmbSky;
uniform vec3 uAmbGround;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uGlow;
uniform float uFogDensity;
uniform float uFogFalloff;
uniform float uHaze;
uniform float uExposure;
uniform float uSnowCover;
uniform float uWet;
uniform vec2 uWindDir;
uniform float uWind;
uniform float uNight;
uniform float uWinLit;

float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float hash13(vec3 p3){ p3 = fract(p3 * 0.1031); p3 += dot(p3, p3.zyx + 31.32); return fract((p3.x + p3.y) * p3.z); }
vec2 hash22(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973)); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.xx + p3.yz) * p3.zy); }
float vnoise(vec2 p){
  vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p){ float s = 0.0; float a = 0.5; for (int i = 0; i < 5; i++){ s += a * vnoise(p); p = mat2(1.6, 1.2, -1.2, 1.6) * p + 17.0; a *= 0.5; } return s / 0.97; }
float fbm3(vec2 p){ float s = 0.0; float a = 0.5; for (int i = 0; i < 3; i++){ s += a * vnoise(p); p = mat2(1.6, 1.2, -1.2, 1.6) * p + 17.0; a *= 0.5; } return s / 0.875; }
float lum(vec3 c){ return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
`;

export const GLSL_FRAG = /* glsl */`
uniform sampler2D uShadowMap;
uniform mat4 uShadowMatrix;
uniform float uShadowStrength;
uniform float uShadowTexel;
uniform vec4 uPL[8];
uniform vec3 uPLC[8];

vec3 skyGradient(vec3 dir){
  float y = dir.y;
  float t = pow(1.0 - clamp(y, 0.0, 1.0), 4.0);
  vec3 c = mix(uZenith, uHorizon, t);
  float mu = max(dot(dir, uSunDir), 0.0);
  float low = clamp(1.0 - max(y, 0.0) * 2.2, 0.0, 1.0);
  c += uGlow * (pow(mu, 4.0) * 0.32 * low + pow(mu, 22.0) * 0.42 + pow(mu, 260.0) * 0.7);
  if (y < 0.0) c = mix(c, uHorizon * 0.92, clamp(-y * 4.0, 0.0, 1.0));
  return c * 1.3;
}
vec3 fogColor(vec3 rd){ return skyGradient(normalize(vec3(rd.x, clamp(rd.y, 0.0, 0.4) * 0.55, rd.z))); }
vec3 applyFog(vec3 col, vec3 wp){
  vec3 rd = wp - uCamPos; float dist = length(rd); rd /= max(dist, 1e-4);
  float k = uFogFalloff;
  float yd = rd.y * dist * k;
  float li = abs(yd) > 1e-4 ? (1.0 - exp(-yd)) / yd : 1.0;
  float od = uFogDensity * exp(-uCamPos.y * k) * dist * li + uHaze * dist;
  return mix(col, fogColor(rd), 1.0 - exp(-od));
}
float getShadow(vec3 wp, vec3 n){
  float ndl = dot(n, uLightDir);
  vec3 p = wp + n * (0.03 + 0.09 * (1.0 - abs(ndl)));
  vec4 sc = uShadowMatrix * vec4(p, 1.0);
  vec3 c = sc.xyz / sc.w;
  if (c.x < 0.0 || c.x > 1.0 || c.y < 0.0 || c.y > 1.0 || c.z > 1.0) return 1.0;
  float edge = smoothstep(0.0, 0.06, min(min(c.x, 1.0 - c.x), min(c.y, 1.0 - c.y)));
  float bias = 0.00035;
  float r = hash12(gl_FragCoord.xy) * 6.2831;
  mat2 rot = mat2(cos(r), sin(r), -sin(r), cos(r));
  vec2 o = vec2(uShadowTexel * 1.6);
  float s = 0.0;
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2(-0.942, -0.399) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2( 0.946, -0.769) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2(-0.094, -0.929) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2( 0.345,  0.294) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2(-0.916,  0.458) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2(-0.815, -0.879) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2(-0.383,  0.277) * o).r);
  s += step(c.z - bias, texture2D(uShadowMap, c.xy + rot * vec2( 0.974,  0.756) * o).r);
  s *= 0.125;
  return mix(1.0, s, edge * uShadowStrength);
}
vec3 localLights(vec3 n, vec3 wp){
  vec3 acc = vec3(0.0);
  for (int i = 0; i < 8; i++){
    vec4 L = uPL[i];
    if (L.w <= 0.0) continue;
    vec3 lv = L.xyz - wp; float d = length(lv);
    if (d > L.w) continue;
    vec3 l = lv / max(d, 1e-3);
    float f = 1.0 - d / L.w;
    float att = f * f / (1.0 + d * d * 0.2);
    acc += uPLC[i] * att * (max(dot(n, l), 0.0) * 0.8 + 0.2);
  }
  return acc;
}
vec3 lighting(vec3 alb, vec3 n, vec3 wp, float sh, float ao, float wrap){
  float ndl = dot(n, uLightDir);
  float diff = clamp((ndl + wrap) / (1.0 + wrap), 0.0, 1.0);
  diff = diff * diff * (3.0 - 2.0 * diff);
  vec3 direct = uLightCol * diff * sh;
  vec3 amb = mix(uAmbGround, uAmbSky, n.y * 0.5 + 0.5) * ao;
  return alb * (direct + amb + localLights(n, wp));
}
vec3 tonemap(vec3 c){
  c *= uExposure;
  c = (c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14);
  return pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2));
}
`;

export function makeMat(vs: string, fs: string, extra: Record<string, THREE.IUniform> = {}, opts: THREE.ShaderMaterialParameters = {}): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: { ...U, ...extra },
    vertexShader: GLSL_COMMON + vs,
    fragmentShader: GLSL_COMMON + GLSL_FRAG + fs,
    ...opts,
  });
}
