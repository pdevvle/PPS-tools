// Sky dome: gradient, sun disc, the waning crescent of 22 December 1989, stars, painted clouds.
import * as THREE from 'three';
import { makeMat } from './uniforms';

const SKY_FS = /* glsl */`
uniform vec3 uCloudLit; uniform vec3 uCloudShade; uniform float uCloudiness; uniform vec2 uCloudOffset;
uniform vec3 uSunDisc; uniform float uStars; uniform float uMoonVis;
varying vec3 vDir;
vec4 clouds(vec3 dir){
  if (dir.y <= 0.0) return vec4(0.0);
  vec2 uv = dir.xz / (dir.y + 0.1) * 0.85 + uCloudOffset;
  vec2 q = uv * vec2(0.42, 0.95);
  float warp = fbm(q * 0.6 + 3.1);
  float n = fbm(q + warp * 1.3);
  float cov = mix(0.66, 0.08, uCloudiness);
  float a = smoothstep(cov, cov + 0.3, n);
  vec2 so = normalize(uSunDir.xz + 1e-4) * 0.1;
  float n2 = fbm(q + so + warp * 1.3);
  float lit = clamp(0.55 + (n - n2) * 4.0, 0.0, 1.0);
  vec3 col = mix(uCloudShade, uCloudLit, lit);
  col += uGlow * pow(max(dot(dir, uSunDir), 0.0), 8.0) * (1.0 - a) * 0.9;
  a *= smoothstep(0.0, 0.2, dir.y);
  col = mix(col, uHorizon, 1.0 - smoothstep(0.0, 0.3, dir.y));
  return vec4(col * 1.3, a);
}
vec3 stars(vec3 dir){
  vec3 p = dir * 150.0;
  vec3 c = floor(p); vec3 f = fract(p);
  float h = hash13(c);
  if (h < 0.93) return vec3(0.0);
  vec3 sp = vec3(hash13(c + 1.3), hash13(c + 2.7), hash13(c + 5.1)) * 0.6 + 0.2;
  float size = 0.12 + 0.2 * pow(fract(h * 31.7), 5.0);
  float tw = 0.7 + 0.3 * sin(uTime * (1.5 + h * 4.0) + h * 40.0);
  return vec3(0.85, 0.9, 1.0) * smoothstep(size, 0.0, length(f - sp)) * tw * (h - 0.93) * 14.0;
}
void main(){
  vec3 dir = normalize(vDir);
  vec3 col = skyGradient(dir);
  if (uStars > 0.01 && dir.y > 0.0) col += stars(dir) * uStars * smoothstep(0.02, 0.3, dir.y) * (1.0 - uCloudiness);
  col += uSunDisc * smoothstep(0.99935, 0.99962, dot(dir, uSunDir));
  float md = dot(dir, uMoonDir);
  float mr = 0.0045;
  if (md > 0.999 && uMoonVis > 0.0){
    vec3 off = dir - uMoonDir * md;
    float r = length(off) / mr;
    if (r < 1.0){
      vec3 nrm = normalize(off / mr - uMoonDir * sqrt(max(1.0 - r * r, 0.0)));
      float lit = smoothstep(-0.05, 0.12, dot(nrm, uSunDir));
      col = mix(col, vec3(0.9, 0.92, 0.95) * 1.6 * (0.8 + 0.2 * vnoise(off.xy * 900.0 + off.z * 500.0)), lit * uMoonVis * smoothstep(1.0, 0.92, r));
    }
  }
  col += vec3(0.25, 0.28, 0.35) * pow(max(md, 0.0), 80.0) * uMoonVis * 0.2;
  vec4 cl = clouds(dir);
  col = mix(col, cl.rgb, cl.a);
  gl_FragColor = vec4(tonemap(col), 1.0);
}`;

export function createSky() {
  const mat = makeMat(
    `varying vec3 vDir; void main(){ vec4 wp = modelMatrix * vec4(position, 1.0); vDir = wp.xyz - uCamPos; gl_Position = projectionMatrix * viewMatrix * wp; }`,
    SKY_FS, { uMoonVis: { value: 0 } }, { side: THREE.BackSide, depthWrite: false, depthTest: false },
  );
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(3000, 48, 24), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = -10;
  return { mesh, mat };
}
