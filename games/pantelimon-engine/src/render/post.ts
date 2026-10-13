// Post: Kuwahara paint filter, a muted East-bloc film grade, vignette, weave and grain.
import * as THREE from 'three';
import { U } from './uniforms';

export function createPost() {
  const mat = new THREE.ShaderMaterial({
    uniforms: { tColor: { value: null }, uTexel: { value: new THREE.Vector2() }, uPaint: { value: 1 }, uAspect: { value: 1 }, uFade: { value: 0 }, uNightGrade: { value: 0 }, uTime: U.uTime, uSmog: { value: 0 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: /* glsl */`
uniform sampler2D tColor; uniform vec2 uTexel; uniform float uPaint; uniform float uAspect;
uniform float uFade; uniform float uNightGrade; uniform float uTime; uniform float uSmog;
varying vec2 vUv;
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y); }
vec3 kuwahara(vec2 uv){
  vec3 m0 = vec3(0.0), m1 = vec3(0.0), m2 = vec3(0.0), m3 = vec3(0.0);
  vec3 s0 = vec3(0.0), s1 = vec3(0.0), s2 = vec3(0.0), s3 = vec3(0.0);
  for (int j = -2; j <= 2; j++) for (int i = -2; i <= 2; i++){
    vec3 c = texture2D(tColor, uv + vec2(float(i), float(j)) * uTexel).rgb;
    vec3 cc = c * c;
    if (i <= 0 && j <= 0){ m0 += c; s0 += cc; }
    if (i >= 0 && j <= 0){ m1 += c; s1 += cc; }
    if (i <= 0 && j >= 0){ m2 += c; s2 += cc; }
    if (i >= 0 && j >= 0){ m3 += c; s3 += cc; }
  }
  m0 /= 9.0; m1 /= 9.0; m2 /= 9.0; m3 /= 9.0;
  vec3 v0 = abs(s0 / 9.0 - m0 * m0), v1 = abs(s1 / 9.0 - m1 * m1), v2 = abs(s2 / 9.0 - m2 * m2), v3 = abs(s3 / 9.0 - m3 * m3);
  float a = v0.r + v0.g + v0.b, b = v1.r + v1.g + v1.b, c = v2.r + v2.g + v2.b, d = v3.r + v3.g + v3.b;
  vec3 r = m0; float mn = a;
  if (b < mn){ mn = b; r = m1; }
  if (c < mn){ mn = c; r = m2; }
  if (d < mn){ mn = d; r = m3; }
  return r;
}
void main(){
  vec3 base = texture2D(tColor, vUv).rgb;
  vec3 col = uPaint > 0.0 ? mix(base, kuwahara(vUv), uPaint * 0.85) : base;
  float l = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(vec3(l), col, 0.9 - uNightGrade * 0.35 - uSmog * 0.15);
  col *= mix(vec3(1.0), vec3(0.86, 0.95, 1.12), uNightGrade * 0.5);
  col = mix(col, col * vec3(1.04, 1.0, 0.92), uSmog * 0.5);
  col = mix(col, col * col * (3.0 - 2.0 * col), 0.25);
  vec2 q = (vUv - 0.5) * vec2(uAspect, 1.0);
  col *= mix(0.7, 1.0, 1.0 - smoothstep(0.45, 1.25, length(q)));
  vec2 fc = gl_FragCoord.xy;
  col *= 0.975 + 0.05 * (vnoise(fc * vec2(0.9, 0.22)) + vnoise(fc * vec2(0.22, 0.9))) * 0.5;
  col += (hash12(fc + fract(uTime * 7.0) * 137.0) - 0.5) * 0.024;
  col *= 1.0 - uFade;
  gl_FragColor = vec4(col, 1.0);
}`,
    depthTest: false, depthWrite: false,
  });
  const scene = new THREE.Scene();
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  quad.frustumCulled = false;
  scene.add(quad);
  return { mat, scene, cam: new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1) };
}
