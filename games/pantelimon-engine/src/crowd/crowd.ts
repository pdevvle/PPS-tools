// ===================================================================
// GPU crowd. Every person is one instance of the same body mesh; the
// vertex shader computes a forward-kinematic pose from the instance's
// pose id and phase (walk cycle, sitting, leaning out of a window,
// marching with a raised fist, carrying a flag...), so animation costs
// nothing on the CPU. Instance attributes carry position, pose and the
// colours of the person's clothes.
//
// Agents: residents placed by the generators (static, posed), and street
// agents moved on the CPU along paths (marchers, pedestrians).
// ===================================================================
import * as THREE from 'three';
import { makeMat } from '../render/uniforms';
import { toGeometry } from '../render/geometry';
import { buildBody, PIVOTS, PARENT } from './body';

export const POSE = { stand: 0, walk: 1, sit: 2, lie: 3, window: 4, cook: 5, chant: 6, phone: 7, read: 8, flag: 9, play: 10, smoke: 11, lean: 12, readwalk: 13 } as const;
export type PoseName = keyof typeof POSE;
export const FLAG = { skirt: 1, coat: 2, flag: 4, indoor: 8, lit: 16, rug: 32 } as const;

export interface Agent {
  x: number; y: number; z: number; yaw: number;
  pose: number; phase: number; speed: number; scale: number;
  top: [number, number, number]; hat: number;
  bottom: [number, number, number]; flags: number;
  skin: [number, number, number]; hairStyle: number;
  hair: [number, number, number];
  // for labels
  name?: string; info?: string; what?: string;
}

const pv = PIVOTS.map((p) => `vec3(${p[0].toFixed(3)}, ${p[1].toFixed(3)}, ${p[2].toFixed(3)})`).join(', ');
const par = PARENT.join(', ');
const CROWD_VS = /* glsl */`
attribute float aMat;
attribute vec2 aAux;
attribute vec4 iA;     // x, y, z, yaw
attribute vec4 iB;     // pose, phase, speed, scale
attribute vec4 iTop;   // rgb, hat
attribute vec4 iBot;   // rgb, flags
attribute vec4 iSkin;  // rgb, hair style
attribute vec4 iHair;  // rgb, seed
varying vec3 vWp; varying vec3 vN; varying vec3 vCol; varying float vPart; varying vec2 vQ; varying float vIndoor; varying vec3 vLp;

const vec3 PIV[11] = vec3[11](${pv});
const int PAR[11] = int[11](${par});

mat3 rx(float a){ float c = cos(a), s = sin(a); return mat3(1.0, 0.0, 0.0, 0.0, c, s, 0.0, -s, c); }
mat3 ry(float a){ float c = cos(a), s = sin(a); return mat3(c, 0.0, -s, 0.0, 1.0, 0.0, s, 0.0, c); }
mat3 rz(float a){ float c = cos(a), s = sin(a); return mat3(c, s, 0.0, -s, c, 0.0, 0.0, 0.0, 1.0); }
bool has(float flags, float bit){ return mod(floor(flags / bit), 2.0) > 0.5; }

void main(){
  int bone = int(aMat + 0.5);
  float part = aAux.x;
  float pose = iB.x, ph = iB.y + uTime * iB.z, seed = iHair.w;
  float flags = iBot.w;
  // ---- garments shown for this person
  bool hide = false;
  if (part > 4.5 && part < 5.5 && abs(aAux.y - iTop.w) > 0.5) hide = true;
  if (part > 2.5 && part < 3.5 && (abs(aAux.y - iSkin.w) > 0.5 || iTop.w > 1.5)) hide = true;
  if (part > 8.5 && part < 9.5 && !has(flags, 2.0)) hide = true;
  if (part > 9.5 && part < 10.5 && (!has(flags, 1.0) || has(flags, 2.0))) hide = true;
  if ((part > 5.5 && part < 7.5) && !has(flags, 4.0)) hide = true;
  if (part > 10.5 && !has(flags, 32.0)) hide = true;
  // ---- pose: rotation (x = swing forward/back, y = twist, z = out to the side) per bone
  vec3 ang[11];
  for (int i = 0; i < 11; i++) ang[i] = vec3(0.0);
  vec3 root = vec3(0.0);
  float rootX = 0.0;
  float idle = sin(uTime * 0.7 + seed * 20.0);
  ang[3].z = 0.08; ang[5].z = -0.08;
  ang[4].x = -0.15; ang[6].x = -0.15;
  ang[2].y = sin(uTime * 0.23 + seed * 9.0) * 0.35;
  ang[1].x = 0.03 + idle * 0.01;
  int P = int(pose + 0.5);
  if (P == 1 || P == 6 || P == 9 || P == 11 || P == 13){
    float s = sin(ph), c = cos(ph);
    ang[7].x = -s * 0.42; ang[9].x = s * 0.42;
    ang[8].x = max(0.0, c) * 0.75 + 0.05; ang[10].x = max(0.0, -c) * 0.75 + 0.05;
    ang[3].x = s * 0.32; ang[5].x = -s * 0.32;
    ang[4].x = -0.25 - max(0.0, s) * 0.2; ang[6].x = -0.25 - max(0.0, -s) * 0.2;
    root.y = abs(c) * 0.035 - 0.02;
    ang[0].y = s * 0.06; ang[1].y = -s * 0.08;
    ang[1].x = 0.06;
    ang[2].y *= 0.3;
    if (P == 6){
      // the raised fist, pumped in time with the chant
      float pump = 0.5 + 0.5 * sin(uTime * 3.6 + seed * 6.0);
      ang[5].x = -2.7 - pump * 0.25; ang[5].z = -0.25; ang[6].x = -0.3 - pump * 0.5;
      ang[2].x = -0.12;
    }
    if (P == 9){ ang[5].x = -0.3; ang[5].z = -0.05; ang[6].x = -1.27; }
    if (P == 11){ float k = smoothstep(0.6, 0.9, sin(uTime * 0.5 + seed * 5.0)); ang[5].x = -0.4 - k * 0.5; ang[6].x = -0.3 - k * 1.9; ang[6].z = k * 0.6; }
    if (P == 13){ ang[3].x = -0.35; ang[5].x = -0.35; ang[4].x = -1.3; ang[6].x = -1.3; ang[3].z = -0.1; ang[5].z = 0.1; ang[2].x = 0.35; }
  } else if (P == 2){
    root.y = -0.47;
    ang[7].x = -1.5; ang[9].x = -1.5; ang[8].x = 1.5; ang[10].x = 1.5;
    ang[3].x = -0.35; ang[5].x = -0.35; ang[4].x = -0.9; ang[6].x = -0.9;
    ang[1].x = -0.05 + idle * 0.02; ang[2].x = 0.1;
  } else if (P == 3){
    rootX = -1.5708; root.y = 0.6; root.z = 0.85;
    ang[2].y = 0.3;
  } else if (P == 4 || P == 12){
    float k = P == 12 ? 1.0 : 0.45;
    ang[1].x = 0.35 * k + 0.1; ang[0].x = 0.1 * k;
    ang[3].x = -1.1 - 0.3 * k; ang[5].x = -1.1 - 0.3 * k; ang[4].x = -0.6 + 0.4 * k; ang[6].x = -0.6 + 0.4 * k;
    ang[2].x = -0.2 * k;
    if (P == 12){ float shake = sin(uTime * 7.0 + seed) * 0.12 * step(0.0, sin(uTime * 0.9 + seed * 3.0)); ang[3].x += shake; ang[5].x += shake; }
  } else if (P == 5){
    ang[3].x = -0.55; ang[5].x = -0.55; ang[4].x = -1.1; ang[6].x = -1.1;
    ang[6].z = sin(uTime * 2.2 + seed) * 0.25;
    ang[1].x = 0.15; ang[2].x = 0.35;
  } else if (P == 7){
    ang[5].x = -0.35; ang[5].z = -0.55; ang[6].x = -2.3; ang[6].z = 0.4;
    ang[2].y = -0.25 + sin(uTime * 0.4 + seed) * 0.2;
  } else if (P == 8){
    ang[3].x = -0.5; ang[5].x = -0.5; ang[4].x = -1.25; ang[6].x = -1.25; ang[3].z = -0.12; ang[5].z = 0.12;
    ang[2].x = 0.4;
  } else if (P == 10){
    // a boy kicking a ball back and forth
    float k = max(0.0, sin(ph));
    ang[9].x = -k * 1.1 + 0.25; ang[10].x = k * 0.3 + 0.2;
    ang[7].x = 0.1; ang[8].x = 0.15;
    ang[3].z = 0.35 + k * 0.2; ang[5].z = -0.35 - k * 0.2;
    ang[1].x = 0.15 - k * 0.1;
    root.y = -0.02;
  } else {
    // standing: weight shifts, arms hang, a hand in a pocket
    ang[7].x = 0.02 * idle; ang[9].x = -0.02 * idle;
    ang[0].z = 0.02 * idle;
    if (fract(seed * 7.3) > 0.5){ ang[5].x = 0.15; ang[6].x = -0.5; ang[6].z = 0.25; }
  }
  // ---- forward kinematics up the bone chain
  vec3 p = position, n = normal;
  int b = bone;
  for (int k = 0; k < 4; k++){
    if (b < 0) break;
    vec3 a = ang[b];
    mat3 R = ry(a.y) * rz(a.z) * rx(a.x);
    p = PIV[b] + R * (p - PIV[b]);
    n = R * n;
    b = PAR[b];
  }
  if (rootX != 0.0){ mat3 R = rx(rootX); p = vec3(0.0, 0.1, 0.0) + R * (p - vec3(0.0, 0.1, 0.0)); n = R * n; }
  p += root;
  p *= iB.w;
  mat3 Y = ry(iA.w);
  vec3 wp = iA.xyz + Y * p;
  vN = normalize(Y * n);
  vWp = wp;
  vLp = position;
  vPart = part;
  vQ = vec2(aAux.y, position.y);
  vIndoor = has(flags, 8.0) ? (has(flags, 16.0) ? 2.0 : 1.0) : 0.0;
  // garment colours
  vec3 col = iSkin.rgb;
  if (part > 0.5 && part < 1.5) col = iTop.rgb;
  else if (part > 1.5 && part < 2.5) col = iBot.rgb;
  else if (part > 2.5 && part < 3.5) col = iHair.rgb;
  else if (part > 3.5 && part < 4.5) col = vec3(0.025, 0.02, 0.018);
  else if (part > 4.5 && part < 5.5) col = iTop.w < 1.5 ? iBot.rgb * 0.8 : (iTop.w < 2.5 ? vec3(0.035, 0.028, 0.022) : (iTop.w < 3.5 ? iTop.rgb * vec3(0.7, 0.9, 1.2) : vec3(0.25, 0.08, 0.06) + iTop.rgb * 0.3));
  else if (part > 7.5 && part < 8.5) col = has(flags, 1.0) ? vec3(0.06, 0.045, 0.04) : iBot.rgb;
  else if (part > 8.5 && part < 9.5) col = iTop.rgb;
  else if (part > 9.5 && part < 10.5) col = iBot.rgb;
  else if (part > 6.5 && part < 7.5) col = vec3(0.16, 0.11, 0.07);
  else if (part > 10.5) col = vec3(0.42, 0.12, 0.08);
  vCol = col;
#ifdef DEPTH
  gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
#else
  gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
#endif
  if (hide) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}`;

const CROWD_FS = /* glsl */`
varying vec3 vWp; varying vec3 vN; varying vec3 vCol; varying float vPart; varying vec2 vQ; varying float vIndoor; varying vec3 vLp;
void main(){
#ifdef DEPTH
  gl_FragColor = vec4(1.0);
#else
  vec3 n = normalize(vN); if (!gl_FrontFacing) n = -n;
  vec3 rd = normalize(vWp - uCamPos);
  float dist = length(vWp - uCamPos);
  vec3 alb = vCol;
  float wrap = 0.45;
  if (vPart > 5.5 && vPart < 6.5){
    // the tricolour with the arms cut out
    float u = clamp((1.85 - vLp.z) / 0.96, 0.0, 1.0); float v = clamp((vLp.x + 0.222) / -0.95, 0.0, 1.0);
    vec2 hd = vec2(u - 0.5, (v - 0.5) * 1.6);
    if (length(hd) < 0.15) discard;
    alb = v < 0.333 ? vec3(0.02, 0.07, 0.36) : (v < 0.666 ? vec3(0.78, 0.55, 0.04) : vec3(0.55, 0.03, 0.03));
    wrap = 0.7;
  } else if (vPart < 0.5 && vLp.y > 1.55 && vLp.z > 0.06){
    // a painted face: brows, eyes, the shadow under the cheekbones
    float ax = abs(vLp.x);
    float eye = 1.0 - smoothstep(0.008, 0.014, length(vec2(ax - 0.035, vLp.y - 1.655)));
    float brow = (1.0 - smoothstep(0.004, 0.009, abs(vLp.y - 1.678 + ax * 0.08))) * step(ax, 0.06) * step(0.012, ax);
    alb = mix(alb, vec3(0.04, 0.03, 0.025), max(eye, brow * 0.8));
    alb *= mix(0.86, 1.0, smoothstep(1.6, 1.64, vLp.y));
  } else if (vPart > 0.5 && vPart < 2.5 || vPart > 8.5){
    alb *= 0.85 + 0.25 * vnoise(vec2(vLp.x * 30.0 + vLp.z * 30.0, vLp.y * 8.0));
  }
  if (vPart > 10.5) alb *= 0.8 + 0.3 * step(0.5, fract((vLp.x + vLp.z) * 9.0));
  // painted light from above
  alb *= mix(0.78, 1.12, smoothstep(-0.65, 0.85, n.y));
  float sh = getShadow(vWp, n);
  vec3 c;
  if (vIndoor > 0.5){
    float diff = clamp((dot(n, uLightDir) + wrap) / (1.0 + wrap), 0.0, 1.0);
    vec3 amb = mix(uAmbGround, uAmbSky, n.y * 0.5 + 0.5) * 0.85;
    vec3 bulb = vec3(1.0, 0.72, 0.42) * step(1.5, vIndoor) * (0.12 + 0.6 * smoothstep(0.0, 0.4, uWinLit));
    c = alb * (uLightCol * diff * sh + amb + bulb + vec3(0.012));
  } else c = lighting(alb, n, vWp, sh, 1.0, wrap);
  float rim = pow(1.0 - max(dot(-rd, n), 0.0), 2.5);
  c += alb * (uAmbSky * 0.55 + uLightCol * 0.15) * rim * (1.0 - smoothstep(12.0, 40.0, dist)) * (vIndoor > 0.5 ? 0.4 : 1.0);
  gl_FragColor = vec4(tonemap(applyFog(c, vWp)), 1.0);
#endif
}`;

export class Crowd {
  readonly cap: number;
  mesh: THREE.Mesh;
  depthMat: THREE.ShaderMaterial;
  private geo: THREE.InstancedBufferGeometry;
  private attrs: Record<'iA' | 'iB' | 'iTop' | 'iBot' | 'iSkin' | 'iHair', THREE.InstancedBufferAttribute>;
  groups = new Map<string, Agent[]>();
  count = 0;
  constructor(cap = 4096) {
    this.cap = cap;
    const body = toGeometry(buildBody().finish());
    const geo = new THREE.InstancedBufferGeometry();
    for (const k of ['position', 'normal', 'aMat', 'aAux']) geo.setAttribute(k, body.getAttribute(k));
    const mk = () => { const a = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4); a.setUsage(THREE.DynamicDrawUsage); return a; };
    this.attrs = { iA: mk(), iB: mk(), iTop: mk(), iBot: mk(), iSkin: mk(), iHair: mk() };
    for (const [k, a] of Object.entries(this.attrs)) geo.setAttribute(k, a);
    geo.instanceCount = 0;
    this.geo = geo;
    const mat = makeMat(CROWD_VS, CROWD_FS, {}, { side: THREE.DoubleSide });
    this.depthMat = makeMat(CROWD_VS, CROWD_FS, {}, { side: THREE.DoubleSide, defines: { DEPTH: 1 } });
    this.mesh = new THREE.Mesh(geo, mat);
    this.mesh.frustumCulled = false;
    this.mesh.userData = { depthMat: this.depthMat, cast: true };
  }
  set(owner: string, agents: Agent[]) { this.groups.set(owner, agents); }
  remove(owner: string) { this.groups.delete(owner); }
  /** Write every agent near the camera into the instance buffers. */
  upload(cx: number, cz: number, radius = 140) {
    const A = this.attrs;
    let i = 0;
    const r2 = radius * radius;
    for (const l of this.groups.values()) for (const a of l) {
      if (i >= this.cap) break;
      const dx = a.x - cx, dz = a.z - cz;
      if (dx * dx + dz * dz > r2) continue;
      A.iA.setXYZW(i, a.x, a.y, a.z, a.yaw);
      A.iB.setXYZW(i, a.pose, a.phase, a.speed, a.scale);
      A.iTop.setXYZW(i, a.top[0], a.top[1], a.top[2], a.hat);
      A.iBot.setXYZW(i, a.bottom[0], a.bottom[1], a.bottom[2], a.flags);
      A.iSkin.setXYZW(i, a.skin[0], a.skin[1], a.skin[2], a.hairStyle);
      A.iHair.setXYZW(i, a.hair[0], a.hair[1], a.hair[2], (a.x * 0.37 + a.z * 0.11) % 1);
      i++;
    }
    for (const a of Object.values(A)) { a.needsUpdate = true; a.clearUpdateRanges(); a.addUpdateRange(0, i * 4); }
    this.geo.instanceCount = i;
    this.count = i;
  }
  /** The person nearest the line of sight, within reach. */
  pick(ox: number, oy: number, oz: number, dx: number, dy: number, dz: number, maxD = 4): Agent | null {
    let best: Agent | null = null, bd = 1e9;
    for (const l of this.groups.values()) for (const a of l) {
      if (!a.name) continue;
      const px = a.x - ox, py = a.y + 1.2 * a.scale - oy, pz = a.z - oz;
      const t = px * dx + py * dy + pz * dz;
      if (t < 0.3 || t > maxD) continue;
      const qx = px - dx * t, qy = py - dy * t, qz = pz - dz * t;
      const off = Math.hypot(qx, qy * 0.5, qz);
      if (off < 0.45 && t < bd) { bd = t; best = a; }
    }
    return best;
  }
}
