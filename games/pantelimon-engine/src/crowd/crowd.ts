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
import type { MeshData } from '../mesh/builder';
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
  // body, after FigureKit's per-person proportions
  face?: number; fem?: boolean; girth?: number; shoulders?: number; hips?: number; belly?: number; age?: number; stoop?: number;
  // for labels
  name?: string; info?: string; what?: string;
}

const pv = PIVOTS.map((p) => `vec3(${p[0].toFixed(3)}, ${p[1].toFixed(3)}, ${p[2].toFixed(3)})`).join(', ');
const par = PARENT.join(', ');
const CROWD_VS = /* glsl */`
attribute float aMat;
attribute vec2 aAux;
attribute vec3 aCol;   // tag, skin shade, skin flush
attribute vec4 iBody;  // girth, shoulders, hips, belly
attribute vec4 iFace;  // face 0–5, woman, age 0–1, stoop
attribute vec4 iA;     // x, y, z, yaw
attribute vec4 iB;     // pose, phase, speed, scale
attribute vec4 iTop;   // rgb, hat
attribute vec4 iBot;   // rgb, flags
attribute vec4 iSkin;  // rgb, hair style
attribute vec4 iHair;  // rgb, seed
varying vec3 vWp; varying vec3 vN; varying vec3 vCol; varying float vPart; varying vec2 vQ; varying float vIndoor; varying vec3 vLp; varying vec2 vTint;

const vec3 PIV[11] = vec3[11](${pv});
const int PAR[11] = int[11](${par});

mat3 rx(float a){ float c = cos(a), s = sin(a); return mat3(1.0, 0.0, 0.0, 0.0, c, s, 0.0, -s, c); }
mat3 ry(float a){ float c = cos(a), s = sin(a); return mat3(c, 0.0, -s, 0.0, 1.0, 0.0, s, 0.0, c); }
mat3 rz(float a){ float c = cos(a), s = sin(a); return mat3(c, s, 0.0, -s, c, 0.0, 0.0, 0.0, 1.0); }
bool has(float flags, float bit){ return mod(floor(flags / bit), 2.0) > 0.5; }
// headscarves: dark wool, faded prints, a black mourning scarf
vec3 basma(float s){ float k = fract(s * 13.7); return k < 0.25 ? vec3(0.035, 0.03, 0.03) : k < 0.5 ? vec3(0.09, 0.05, 0.035) : k < 0.75 ? vec3(0.06, 0.06, 0.075) : vec3(0.12, 0.035, 0.03); }

void main(){
  int bone = int(aMat + 0.5);
  float part = aAux.x;
  float pose = iB.x, ph = iB.y + uTime * iB.z, seed = iHair.w;
  float flags = iBot.w;
  // ---- garments shown for this person
  bool hide = false;
  bool fem = iFace.y > 0.5;
  float tag = aCol.x;
  if (tag > -0.5 && tag < 19.5 && abs(tag - (iFace.x + (fem ? 8.0 : 0.0))) > 0.5) hide = true;   // one of twelve faces
  if (tag > 19.5 && (tag > 20.5) != fem) hide = true;                                            // a man's or a woman's body
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
  // ---- this person's build (FigureKit's P.body, applied to the shared mesh)
  float girth = iBody.x, sw = iBody.y, hp = iBody.z, belly = iBody.w, stoop = iFace.w;
  vec3 pv[11];
  for (int i = 0; i < 11; i++) pv[i] = PIV[i];
  float shX = fem ? 0.175 : 0.19, lgX = fem ? 0.082 : 0.078;
  pv[3].x = shX * sw; pv[4].x = shX * sw; pv[5].x = -shX * sw; pv[6].x = -shX * sw;
  pv[7].x = lgX * hp; pv[8].x = lgX * hp; pv[9].x = -lgX * hp; pv[10].x = -lgX * hp;
  vec3 p = position, n = normal;
  if (bone >= 3 && bone <= 10) {
    // limbs: thicker or thinner about their own axis, and carried with the shoulders or hips
    float ax = bone <= 6 ? (p.x > 0.0 ? shX : -shX) : (p.x > 0.0 ? lgX : -lgX);
    float g = mix(1.0, girth, part < 0.5 ? 0.35 : 1.0);
    p.x = pv[bone].x + (p.x - ax) * g; p.z *= g;
  } else if (bone <= 1) {
    float shoulder = smoothstep(1.2, 1.39, p.y), hipBand = 1.0 - smoothstep(1.0, 1.16, p.y);
    p.x *= girth * mix(mix(1.0, hp, hipBand), sw, shoulder);
    p.z *= mix(1.0, girth, 0.8);
    // a belly under the coat
    float bz = belly * 0.075 * exp(-pow((p.y - 1.1) / 0.1, 2.0)) * smoothstep(-0.02, 0.06, p.z);
    p.z += bz; p.x *= 1.0 + bz * 1.5;
  }
  // age: a stoop at the shoulders, the head pushed forward, soft knees
  ang[1].x += stoop * 0.38; ang[2].x -= stoop * 0.25; ang[8].x += stoop * 0.12; ang[10].x += stoop * 0.12; root.y -= stoop * 0.04;
  // ---- forward kinematics up the bone chain
  int b = bone;
  for (int k = 0; k < 4; k++){
    if (b < 0) break;
    vec3 a = ang[b];
    mat3 R = ry(a.y) * rz(a.z) * rx(a.x);
    p = pv[b] + R * (p - pv[b]);
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
  else if (part > 4.5 && part < 5.5) col = iTop.w < 1.5 ? iBot.rgb * 0.8 : (iTop.w < 2.5 ? vec3(0.035, 0.028, 0.022) : (iTop.w < 3.5 ? iTop.rgb * vec3(0.7, 0.9, 1.2) : basma(seed)));
  else if (part > 7.5 && part < 8.5) col = has(flags, 1.0) ? vec3(0.06, 0.045, 0.04) : iBot.rgb;
  else if (part > 8.5 && part < 9.5) col = iTop.rgb;
  else if (part > 9.5 && part < 10.5) col = iBot.rgb;
  else if (part > 6.5 && part < 7.5) col = vec3(0.16, 0.11, 0.07);
  else if (part > 10.5) col = vec3(0.42, 0.12, 0.08);
  if (part > 11.5 && part < 12.5) col = iHair.rgb * (iFace.z > 0.7 ? 1.6 : 0.8);
  if (part > 12.5) col = vec3(0.03, 0.025, 0.02);
  vCol = col;
  vTint = part < 0.5 ? aCol.yz : vec2(1.0, 0.0);
#ifdef INK
  // the ink stroke: a back-facing shell pushed out in view space, a constant width on screen
  vec4 mv = viewMatrix * vec4(wp, 1.0);
  vec3 vn = normalize(mat3(viewMatrix) * vN);
  mv.xyz += vn * 0.0075 * max(-mv.z, 0.5);  // wide enough to survive the paint filter
  gl_Position = projectionMatrix * mv;
#else
  gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
#endif
#ifdef INK
  if ((part > 5.5 && part < 7.5) || part > 10.5) hide = true;   // no stroke on the flag, its pole or the rug
#endif
  if (hide) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}`;

const CROWD_FS = /* glsl */`
varying vec3 vWp; varying vec3 vN; varying vec3 vCol; varying float vPart; varying vec2 vQ; varying float vIndoor; varying vec3 vLp; varying vec2 vTint;
void main(){
#ifdef DEPTH
  gl_FragColor = vec4(1.0);
#elif defined(INK)
  // dark brown ink, thinning out with distance and fog
  float dist = length(vWp - uCamPos);
  if (dist > 45.0) discard;
  vec3 ink = vec3(0.045, 0.035, 0.028) * (0.6 + 0.4 * (uAmbSky.r + uLightCol.r * 0.3));
  gl_FragColor = vec4(tonemap(applyFog(ink, vWp)), 1.0);
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
  } else if (vPart < 0.5){
    // FigureKit's painted face: shadowed sockets, redder lips and cheeks, baked into the head
    alb *= vTint.x;
    alb = mix(alb, alb * vec3(1.25, 0.72, 0.68), clamp(vTint.y, 0.0, 1.0));
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
  } else {
    // FigureKit's inked toon: light falls in three bands, softened here to sit in the painted street
    float ndl = clamp((dot(n, uLightDir) + wrap) / (1.0 + wrap), 0.0, 1.0) * sh;
    float band = 0.12 + 0.5 * smoothstep(0.1, 0.18, ndl) + 0.38 * smoothstep(0.55, 0.63, ndl);
    vec3 amb = mix(uAmbGround, uAmbSky, n.y * 0.5 + 0.5);
    c = alb * (uLightCol * band + amb + localLights(n, vWp));
  }
  float rim = pow(1.0 - max(dot(-rd, n), 0.0), 2.5);
  c += alb * (uAmbSky * 0.55 + uLightCol * 0.15) * rim * (1.0 - smoothstep(12.0, 40.0, dist)) * (vIndoor > 0.5 ? 0.4 : 1.0);
  gl_FragColor = vec4(tonemap(applyFog(c, vWp)), 1.0);
#endif
}`;

/** Weld identical vertices into an indexed geometry (the builder emits flat triangle lists). */
function weld(md: MeshData, tris: number[]): THREE.BufferGeometry {
  const map = new Map<string, number>();
  const pos: number[] = [], nrm: number[] = [], mat: number[] = [], aux: number[] = [], col: number[] = [], idx: number[] = [];
  for (const t of tris) for (let k = 0; k < 3; k++) {
    const i = t * 3 + k;
    const key = [md.position[i * 3], md.position[i * 3 + 1], md.position[i * 3 + 2], md.normal[i * 3], md.normal[i * 3 + 1], md.normal[i * 3 + 2], md.mat[i], md.aux[i * 2], md.aux[i * 2 + 1], md.col[i * 3 + 1], md.col[i * 3 + 2]].map((v) => v.toFixed(4)).join(',');
    let j = map.get(key);
    if (j === undefined) {
      j = pos.length / 3; map.set(key, j);
      pos.push(md.position[i * 3], md.position[i * 3 + 1], md.position[i * 3 + 2]); nrm.push(md.normal[i * 3], md.normal[i * 3 + 1], md.normal[i * 3 + 2]);
      mat.push(md.mat[i]); aux.push(md.aux[i * 2], md.aux[i * 2 + 1]); col.push(md.col[i * 3], md.col[i * 3 + 1], md.col[i * 3 + 2]);
    }
    idx.push(j);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('aMat', new THREE.Float32BufferAttribute(mat, 1));
  g.setAttribute('aAux', new THREE.Float32BufferAttribute(aux, 2));
  g.setAttribute('aCol', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  return g;
}

type AttrName = 'iA' | 'iB' | 'iTop' | 'iBot' | 'iSkin' | 'iHair' | 'iBody' | 'iFace';
interface Part { mesh: THREE.Mesh; ink: THREE.Mesh; geo: THREE.InstancedBufferGeometry; attrs: Record<AttrName, THREE.InstancedBufferAttribute>; cap: number; n: number }

export class Crowd {
  /** Everything to add to the scene: one body mesh per sex and one head mesh per face, each with its ink pass. */
  group = new THREE.Group();
  depthMat: THREE.ShaderMaterial;
  private parts: Part[] = [];
  groups = new Map<string, Agent[]>();
  count = 0;
  vertsPerPerson = 0;
  constructor(cap = 4096) {
    const md = buildBody().finish();
    // route each triangle by its tag: bodies (with hats, flags and rugs on both), and the twelve heads
    const lists: number[][] = Array.from({ length: 14 }, () => []);
    for (let t = 0; t < md.count / 3; t++) {
      const tag = Math.round(md.col[t * 9]);
      if (tag === 20) lists[0].push(t); else if (tag === 21) lists[1].push(t);
      else if (tag < 0) { lists[0].push(t); lists[1].push(t); }
      else lists[2 + (tag >= 8 ? 6 + tag - 8 : tag)].push(t);
    }
    const mat = makeMat(CROWD_VS, CROWD_FS, {}, { side: THREE.DoubleSide });
    this.depthMat = makeMat(CROWD_VS, CROWD_FS, {}, { side: THREE.DoubleSide, defines: { DEPTH: 1 } });
    const inkMat = makeMat(CROWD_VS, CROWD_FS, {}, { side: THREE.BackSide, defines: { INK: 1 } });
    lists.forEach((tris, pi) => {
      const base = weld(md, tris);
      const pcap = pi < 2 ? cap : Math.ceil(cap / 4);
      const geo = new THREE.InstancedBufferGeometry();
      geo.index = base.index;
      for (const k of ['position', 'normal', 'aMat', 'aAux', 'aCol']) geo.setAttribute(k, base.getAttribute(k));
      const mk = () => { const a = new THREE.InstancedBufferAttribute(new Float32Array(pcap * 4), 4); a.setUsage(THREE.DynamicDrawUsage); return a; };
      const attrs = { iA: mk(), iB: mk(), iTop: mk(), iBot: mk(), iSkin: mk(), iHair: mk(), iBody: mk(), iFace: mk() };
      for (const [k, a] of Object.entries(attrs)) geo.setAttribute(k, a);
      geo.instanceCount = 0;
      const mesh = new THREE.Mesh(geo, mat), ink = new THREE.Mesh(geo, inkMat);
      mesh.frustumCulled = false; ink.frustumCulled = false;
      mesh.userData = { depthMat: this.depthMat, cast: true }; ink.userData = { cast: false };
      this.group.add(mesh, ink);
      this.parts.push({ mesh, ink, geo, attrs, cap: pcap, n: 0 });
      if (pi === 0 || pi === 2) this.vertsPerPerson += base.getAttribute('position').count;
    });
  }
  /** Give someone a build and a face the first time they're drawn: steady per person, varied across the crowd. */
  private body(a: Agent) {
    if (a.face !== undefined) return;
    let h = 2166136261;
    const key = a.name || `${a.x.toFixed(1)},${a.z.toFixed(1)}`;
    for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
    let x = h >>> 0 || 1;
    const r = () => { x = (Math.imul(x, 1664525) + 1013904223) >>> 0; return x / 4294967296; };
    const fem = a.fem ?? ((a.flags & FLAG.skirt) !== 0 || a.hairStyle > 0);
    a.fem = fem;
    a.face = Math.floor(r() * 6);
    const age = a.age ?? (a.scale < 0.85 ? 0.05 : 0.2 + r() * 0.7);
    a.age = age;
    a.girth = 0.88 + r() * 0.26 + age * 0.08;
    a.shoulders = fem ? 0.94 + r() * 0.1 : 0.94 + r() * 0.16;
    a.hips = fem ? 1.0 + r() * 0.12 : 0.94 + r() * 0.1;
    a.belly = Math.max(0, r() * 1.2 - 0.4) * (0.4 + age);
    a.stoop = age > 0.7 ? (age - 0.7) * 2.2 * r() : 0;
  }
  set(owner: string, agents: Agent[]) { this.groups.set(owner, agents); }
  remove(owner: string) { this.groups.delete(owner); }
  /** Write every agent near the camera into the instance buffers of their body and their head. */
  upload(cx: number, cz: number, radius = 140) {
    for (const p of this.parts) p.n = 0;
    const r2 = radius * radius;
    let total = 0;
    const put = (p: Part, a: Agent) => {
      if (p.n >= p.cap) return;
      const A = p.attrs, i = p.n++;
      A.iA.setXYZW(i, a.x, a.y, a.z, a.yaw);
      A.iB.setXYZW(i, a.pose, a.phase, a.speed, a.scale);
      A.iTop.setXYZW(i, a.top[0], a.top[1], a.top[2], a.hat);
      A.iBot.setXYZW(i, a.bottom[0], a.bottom[1], a.bottom[2], a.flags);
      A.iSkin.setXYZW(i, a.skin[0], a.skin[1], a.skin[2], a.hairStyle);
      A.iHair.setXYZW(i, a.hair[0], a.hair[1], a.hair[2], (a.x * 0.37 + a.z * 0.11) % 1);
      A.iBody.setXYZW(i, a.girth!, a.shoulders!, a.hips!, a.belly!);
      A.iFace.setXYZW(i, a.face!, a.fem ? 1 : 0, a.age!, a.stoop!);
    };
    for (const l of this.groups.values()) for (const a of l) {
      const dx = a.x - cx, dz = a.z - cz;
      if (dx * dx + dz * dz > r2) continue;
      this.body(a);
      put(this.parts[a.fem ? 1 : 0], a);
      put(this.parts[2 + (a.fem ? 6 : 0) + a.face!], a);
      total++;
    }
    for (const p of this.parts) {
      for (const at of Object.values(p.attrs)) { at.needsUpdate = true; at.clearUpdateRanges(); at.addUpdateRange(0, p.n * 4); }
      p.geo.instanceCount = p.n;
      p.mesh.visible = p.ink.visible = p.n > 0;
    }
    this.count = total;
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
