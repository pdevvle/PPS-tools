// ===================================================================
// The world material: every opaque surface (ground, facades, interiors,
// furniture, props) shares one painterly shader. The surface is picked
// per vertex with aMat (codes in mesh/mat.ts).
//
// Engine hooks on top of the street demo's shader:
//  - HIDEABLE: aBid indexes uHide; a far shell is collapsed once its
//    building's detailed version is on screen.
//  - aSnow < 0 marks interior vertices (−1 unlit room, −2 lit room):
//    less sky light, a warm bulb at night, no snow.
//  - INST_ATTR: furniture instances carry their room's light in aInst.
//  - Window seeds carry flags: +2 room lit, +4 TV on, +8 a plug behind
//    real glass (no painted frame or reflection).
// ===================================================================
import * as THREE from 'three';
import { makeMat } from './uniforms';

const WORLD_VS = /* glsl */`
attribute vec3 aCol;
attribute float aMat;
attribute vec2 aUv;
attribute float aSeed;
attribute float aSnow;
attribute float aAo;
attribute vec2 aAux;
#ifdef HIDEABLE
attribute float aBid;
uniform sampler2D uHide;
#endif
#ifdef INST_ATTR
attribute vec2 aInst;
#endif
varying vec3 vWp; varying vec3 vN; varying vec3 vCol; varying vec3 vLp;
varying float vMat; varying float vSeed; varying float vSnow; varying float vAo;
varying vec2 vUv; varying vec2 vAux;
void main(){
  mat4 m = modelMatrix;
#ifdef USE_INSTANCING
  m = modelMatrix * instanceMatrix;
#endif
  vec4 wp = m * vec4(position, 1.0);
  vec3 wn = normalize(mat3(m) * normal);
  float seed = aSeed;
  float snow = aSnow;
#ifdef INST_ATTR
  snow = -aInst.x;
#endif
#ifdef USE_INSTANCING
  vec3 ip = vec3(m[3][0], m[3][1], m[3][2]);
  seed = fract(aSeed + hash12(ip.xz) * 7.31) + floor(aSeed);
  if (aAux.x > 0.0 && abs(aMat - 20.0) < 0.5) {
    // bare branches sway in the wind
    float ph = hash12(ip.xz + 3.7) * 6.2831;
    float g = sin(uTime * 1.3 + ph) * 0.6 + sin(uTime * 3.1 + ph * 2.0) * 0.25 + 0.45;
    wp.xz += uWindDir * aAux.x * (0.03 + 0.2 * uWind) * g;
  }
#else
  // flags and hanging laundry ripple in the wind
  if (abs(aMat - 26.0) < 0.5 || abs(aMat - 27.0) < 0.5 || abs(aMat - 46.0) < 0.5) {
    float w = aAux.y;
    float ph = aSeed * 17.0;
    float wave = sin(aUv.x * 4.0 - uTime * (2.2 + uWind * 3.0) + ph) * 0.6 + sin(aUv.x * 9.0 + aUv.y * 3.0 - uTime * 4.1 + ph) * 0.25;
    wp.xyz += wn * wave * w * (0.025 + 0.09 * uWind);
    wp.xz += uWindDir * w * (0.02 + 0.12 * uWind);
  }
#endif
  vWp = wp.xyz; vN = wn;
  vCol = aCol; vLp = position; vMat = aMat; vSeed = seed; vSnow = snow; vAo = aAo; vUv = aUv; vAux = aAux;
  gl_Position = projectionMatrix * viewMatrix * wp;
#ifdef HIDEABLE
  if (aBid >= 0.0) {
    int bi = int(aBid + 0.5);
    if (texelFetch(uHide, ivec2(bi % 1024, bi / 1024), 0).r > 0.5) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  }
#endif
}
`;

const WORLD_FS = /* glsl */`
varying vec3 vWp; varying vec3 vN; varying vec3 vCol; varying vec3 vLp;
varying float vMat; varying float vSeed; varying float vSnow; varying float vAo;
varying vec2 vUv; varying vec2 vAux;

float gDist; float gFine; vec3 gRd;
float aaf(vec2 p){ vec2 w = fwidth(p); return 1.0 - smoothstep(0.18, 0.55, max(w.x, w.y)); }

float voronoiEdge(vec2 p){
  vec2 n = floor(p); vec2 f = fract(p);
  float d1 = 8.0; float d2 = 8.0;
  for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++){
    vec2 g = vec2(float(i), float(j));
    vec2 r = g + hash22(n + g) - f;
    float d = dot(r, r);
    if (d < d1){ d2 = d1; d1 = d; } else if (d < d2){ d2 = d; }
  }
  return sqrt(d2) - sqrt(d1);
}
vec3 reflectEnv(vec3 R){
  vec3 s = skyGradient(normalize(vec3(R.x, max(R.y, 0.02), R.z)));
  float occl = smoothstep(0.02, 0.4, R.y);
  return mix(uAmbSky * 0.35 + uAmbGround * 0.25, s, occl);
}
// flickering blue-grey light of a television: on 22 December everyone was watching TVR
vec3 tvLight(float seed){
  float t = uTime * 1.7 + seed * 40.0;
  float f = 0.55 + 0.25 * sin(t * 3.1) * sin(t * 1.3 + 2.0) + 0.2 * step(0.7, fract(sin(floor(t * 2.0) * 12.9) * 43758.5));
  return vec3(0.42, 0.52, 0.75) * f;
}

// ---------- interior behind a window (interior mapping in window space, metres)
vec3 roomColor(vec3 ro, vec3 rd, vec2 size, float seed, float lit, float tv, bool shop){
  float D = shop ? 4.5 : 3.4;
  vec3 bmin = vec3(-0.9, shop ? -0.4 : -1.0, 0.0);
  vec3 bmax = vec3(size.x + 0.9, size.y + (shop ? 0.4 : 0.75), D);
  vec3 inv = 1.0 / rd;
  vec3 t1 = (bmin - ro) * inv; vec3 t2 = (bmax - ro) * inv;
  vec3 tf = max(t1, t2);
  float t = min(min(tf.x, tf.y), tf.z);
  vec3 p = ro + rd * t;
  float h1 = hash12(vec2(seed * 31.0, 1.7)); float h2 = hash12(vec2(seed * 17.0, 9.1)); float h3 = hash12(vec2(seed * 7.0, 4.4));
  vec3 wall = mix(mix(vec3(0.42, 0.36, 0.26), vec3(0.30, 0.36, 0.32), h1), vec3(0.42, 0.33, 0.30), h2 * 0.6);
  vec3 c;
  if (shop){
    wall = vec3(0.34, 0.36, 0.33);
    if (t == tf.z){
      float shelfY = fract((p.y - 0.25) / 0.48);
      float shelf = step(0.88, shelfY);
      c = wall * (0.85 + 0.15 * vnoise(p.xy * 3.0));
      float row = floor((p.y - 0.25) / 0.48);
      float cans = 0.0;
      if (row >= 0.0 && row < 4.0 && hash12(vec2(row, seed)) > 0.45){
        float lx = fract(p.x / 1.1 + hash12(vec2(row, seed + 2.0)));
        float tri = step(abs(lx - 0.5) * 2.0, 1.0 - shelfY * 1.4) * step(shelfY, 0.6);
        cans = tri * step(0.2, fract(lx * 9.0)) * step(0.18, fract(shelfY * 4.5));
      }
      c = mix(c, vec3(0.55, 0.42, 0.22), cans * 0.85);
      c = mix(c, vec3(0.16, 0.13, 0.1), shelf);
    } else if (t == tf.y){
      c = rd.y < 0.0 ? vec3(0.2, 0.19, 0.17) : vec3(0.45, 0.45, 0.42);
    } else c = wall * 0.8;
    c = mix(c, vec3(0.22, 0.16, 0.11), step(p.z, 1.6) * step(1.0, p.z) * step(p.y, 0.95));
    vec3 fl = vec3(0.75, 0.85, 0.8) * (0.25 + lit * 1.4);
    return c * mix(uAmbSky * 0.35 + uLightCol * 0.05, fl, 0.6) * mix(1.0, 0.6, p.z / D);
  }
  if (t == tf.z){
    float stripe = 0.9 + 0.1 * step(0.5, fract(p.x * (3.0 + h3 * 4.0)));
    float flower = smoothstep(0.75, 0.9, vnoise(p.xy * 9.0 + seed * 10.0));
    c = wall * stripe * (1.0 - flower * 0.15);
    float wx0 = mix(-0.6, size.x * 0.5, h2);
    float ward = step(wx0, p.x) * step(p.x, wx0 + 1.4) * step(p.y, size.y + 0.25);
    c = mix(c, vec3(0.16, 0.10, 0.07) * (0.85 + 0.15 * step(0.04, abs(fract((p.x - wx0) / 0.7) - 0.5))), ward * step(0.35, h3));
    float pic = step(abs(p.x - (wx0 + 2.0)), 0.25) * step(abs(p.y - (size.y * 0.75)), 0.18);
    c = mix(c, vec3(0.3, 0.22, 0.12), pic * step(h3, 0.7));
  } else if (t == tf.y){
    if (rd.y < 0.0){
      c = mix(vec3(0.22, 0.13, 0.08), vec3(0.32, 0.14, 0.1), step(0.5, h1));
      c *= 0.85 + 0.15 * step(0.5, fract(p.x * 4.0 + floor(p.z * 1.5) * 0.5));
    } else {
      c = vec3(0.62, 0.6, 0.55);
      vec2 lp = vec2(size.x * 0.5, D * 0.5);
      c += vec3(1.0, 0.7, 0.35) * (1.0 - smoothstep(0.0, 0.12, length(p.xz - lp))) * lit * 4.0;
    }
  } else c = wall * 0.82;
  float depthShade = mix(1.0, 0.55, p.z / D);
  vec3 dayLight = uAmbSky * 0.28 + uLightCol * 0.06;
  vec2 bulb = vec2(size.x * 0.5, bmax.y - 0.3);
  float bd = length(vec3(p.x - bulb.x, p.y - bulb.y, p.z - D * 0.5));
  vec3 nightLight = vec3(1.0, 0.62, 0.3) * (1.1 / (1.0 + bd * bd * 0.35)) * lit;
  vec3 tvl = tv * tvLight(seed) * (0.5 + 0.5 * uNight) * (1.2 / (1.0 + p.z * 0.5));
  return c * (dayLight * depthShade + nightLight + tvl);
}

struct Surf { vec3 alb; vec3 n; float ao; float spec; float gloss; vec3 emis; float wrap; float snowable; };

void matPanel(inout Surf s, vec2 uv, vec2 psize, float seed, vec3 wp){
  vec2 q = uv / max(psize, vec2(0.1));
  vec2 f = fract(q);
  vec2 dm = min(f, 1.0 - f) * psize;
  float joint = 1.0 - smoothstep(0.012, 0.032 + 0.02 * (1.0 - gFine), min(dm.x, dm.y));
  float big = fbm3(uv * vec2(0.22, 0.4) + seed * 13.0);
  float fine = vnoise(uv * 7.0) * 0.5 + vnoise(uv * 21.0) * 0.5;
  vec3 a = s.alb * (0.84 + 0.26 * big) * mix(1.0, 0.92 + 0.14 * fine, gFine);
  a *= 0.92 + 0.14 * hash12(floor(q) + seed * 7.0);
  float streak = vnoise(vec2(uv.x * 2.6, uv.y * 0.1 + seed * 3.0));
  streak = smoothstep(0.55, 0.9, streak) * (0.4 + 0.6 * f.y);
  a *= 1.0 - streak * 0.26;
  float run = (1.0 - smoothstep(0.0, 0.18, dm.x)) * smoothstep(0.5, 0.85, vnoise(vec2(uv.x * 9.0, uv.y * 0.6)));
  a *= 1.0 - run * 0.2;
  a *= mix(0.7, 1.0, smoothstep(0.0, 1.6, wp.y));
  s.alb = mix(a, a * 0.42, joint * aaf(q * 2.0));
  s.ao *= 1.0 - joint * 0.3;
}

void main(){
  int mat = int(vMat + 0.5);
  vec3 wp = vWp;
  vec3 toP = wp - uCamPos;
  gDist = length(toP);
  gRd = toP / max(gDist, 1e-4);
  gFine = 1.0 - smoothstep(14.0, 60.0, gDist);
  bool indoor = vSnow < -0.5;
  float roomLit = step(1.5, -vSnow);

  Surf s;
  s.alb = vCol; s.n = normalize(vN); s.ao = vAo; s.spec = 0.0; s.gloss = 0.0; s.emis = vec3(0.0); s.wrap = 0.2; s.snowable = max(vSnow, 0.0);
  if (!gl_FrontFacing) s.n = -s.n;
  vec2 uv = vUv;
  float seed = fract(vSeed);
  float flags = floor(vSeed);
  bool done = false;
  vec3 outCol = vec3(0.0);

  if (mat == 1){
    matPanel(s, uv, vAux, seed, wp);
  } else if (mat == 2 || mat == 13){
    bool shop = (mat == 13);
    bool plug = flags >= 8.0;
    float litF = mod(floor(flags / 2.0), 2.0);
    float tvF = mod(floor(flags / 4.0), 2.0);
    vec2 size = vAux;
    vec3 n = s.n;
    vec3 T = normalize(cross(vec3(0.0, 1.0, 0.0), n));
    vec3 B = vec3(0.0, 1.0, 0.0);
    vec3 d = vec3(dot(gRd, T), dot(gRd, B), -dot(gRd, n));
    d.z = max(d.z, 0.03);
    float rev = (shop || plug) ? 0.0 : 0.13;
    vec2 g = uv + d.xy * (rev / d.z);
    float sh = getShadow(wp, n);
    float lit = litF * smoothstep(0.0, 0.35, uWinLit);
    if (!plug && (g.x < 0.0 || g.x > size.x || g.y < 0.0 || g.y > size.y)){
      vec3 rn = g.x < 0.0 ? T : (g.x > size.x ? -T : (g.y < 0.0 ? B : -B));
      outCol = lighting(vec3(0.30, 0.29, 0.27) * (0.85 + 0.2 * vnoise(g * 9.0)), rn, wp, sh * 0.7, 0.55, 0.3);
    } else {
      float fw = shop ? 0.05 : 0.065;
      float edge = min(min(g.x, size.x - g.x), min(g.y, size.y - g.y));
      bool twoSash = size.x > 0.95 && !shop;
      float mull = twoSash ? abs(g.x - size.x * 0.5) : 9.0;
      float tran = shop ? abs(g.y - size.y * 0.82) : abs(g.y - size.y * 0.74);
      float fr = plug ? 1.0 : min(edge - fw, min(mull - 0.04, tran - 0.03));
      if (fr < 0.0){
        vec3 fa = vCol * (0.78 + 0.22 * vnoise(g * 22.0 + seed));
        float peel = smoothstep(0.72, 0.8, vnoise(g * vec2(40.0, 7.0) + seed * 5.0));
        fa = mix(fa, vec3(0.16, 0.14, 0.12), peel * (shop ? 0.0 : 0.7));
        fa *= 1.0 - smoothstep(-0.012, -0.004, fr) * 0.35;
        outCol = lighting(fa, n, wp, sh, 0.85, 0.2);
      } else {
        vec3 inside = roomColor(vec3(g, 0.0), normalize(d), size, seed, lit, tvF, shop);
        if (!shop){
          // lace net curtain (perdea), sometimes heavy drapes (draperii)
          float hc = hash12(vec2(seed * 13.0, 5.5));
          float cover = step(0.18, hc);
          vec2 cg = g + d.xy * (0.06 / d.z);
          float folds = 0.78 + 0.22 * sin(cg.x * 34.0 + vnoise(cg * 4.0) * 3.0);
          float lace = (0.45 + 0.35 * smoothstep(0.4, 0.7, vnoise(cg * 26.0))) * folds;
          float gap = (hc > 0.75) ? step(abs(cg.x - size.x * 0.5), 0.12 + 0.25 * (hc - 0.75) * 4.0) : 0.0;
          vec3 laceCol = vec3(0.62, 0.6, 0.54) * (uAmbSky * 0.55 + uLightCol * 0.12) + vec3(1.0, 0.62, 0.3) * lit * 0.55 + tvF * tvLight(seed) * 0.3;
          inside = mix(inside, laceCol, lace * cover * (1.0 - gap) * 0.85);
          float hd = hash12(vec2(seed * 5.0, 8.8));
          if (hd > 0.45){
            float dw = 0.16 + 0.12 * hd;
            float drape = step(cg.x, dw) + step(size.x - dw, cg.x);
            vec3 dc = hd > 0.8 ? vec3(0.25, 0.06, 0.05) : (hd > 0.62 ? vec3(0.32, 0.22, 0.06) : vec3(0.12, 0.14, 0.1));
            dc *= 0.7 + 0.3 * sin(cg.x * 60.0);
            inside = mix(inside, dc * (uAmbSky * 0.5 + vec3(1.0, 0.6, 0.3) * lit * 0.6), min(drape, 1.0));
          }
        }
        if (plug) outCol = inside;
        else {
          vec3 R = reflect(gRd, n);
          float fres = 0.07 + 0.55 * pow(1.0 - abs(dot(gRd, n)), 4.0);
          outCol = mix(inside, reflectEnv(R) * 0.8, fres) + vnoise(g * 6.0 + seed * 3.0) * 0.06 * uAmbSky * 0.5;
          outCol += uLightCol * pow(max(dot(R, uLightDir), 0.0), 220.0) * sh * 3.0;
        }
      }
    }
    done = true;
  } else if (mat == 3){
    vec2 p = uv;
    s.alb *= 0.82 + 0.3 * fbm3(p * 0.6 + seed * 5.0);
    float bare = smoothstep(0.66, 0.7, fbm3(p * 0.9 + seed * 9.0));
    vec2 bq = vec2(p.x / 0.25 + mod(floor(p.y / 0.065), 2.0) * 0.5, p.y / 0.065);
    vec2 bf = fract(bq);
    float mortar = (step(bf.x, 0.06) + step(bf.y, 0.14)) * aaf(bq);
    vec3 brick = mix(vec3(0.24, 0.09, 0.05), vec3(0.32, 0.14, 0.08), hash12(floor(bq)));
    brick = mix(brick, vec3(0.3, 0.29, 0.27), min(mortar, 1.0));
    s.alb = mix(s.alb, brick, bare * (indoor ? 0.0 : 1.0));
    if (!indoor) s.alb *= mix(0.65, 1.0, smoothstep(0.0, 1.0, wp.y));
  } else if (mat == 4){
    vec2 bq = vec2(uv.x / 0.25 + mod(floor(uv.y / 0.065), 2.0) * 0.5, uv.y / 0.065);
    vec2 bf = fract(bq);
    float mortar = max(1.0 - smoothstep(0.03, 0.07, bf.x), 1.0 - smoothstep(0.08, 0.16, bf.y)) * gFine * aaf(bq);
    s.alb *= 0.75 + 0.45 * hash12(floor(bq) + seed);
    s.alb = mix(s.alb, vec3(0.28, 0.27, 0.25), mortar);
  } else if (mat == 29){
    vec2 q = uv / 0.05;
    vec2 f = fract(q);
    float grout = (1.0 - smoothstep(0.0, 0.12, min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y)))) * gFine * aaf(q);
    s.alb *= 0.75 + 0.45 * hash12(floor(q)) * aaf(q) + 0.22 * (1.0 - aaf(q));
    s.alb = mix(s.alb, vec3(0.3, 0.3, 0.28), grout * 0.8);
    s.alb *= 0.85 + 0.2 * fbm3(uv * 0.5);
    s.spec = 0.15;
  } else if (mat == 5 || mat == 7){
    bool side = (mat == 7);
    vec2 p = wp.xz;
    float n1 = fbm3(p * 0.3);
    float grain = mix(0.5, vnoise(p * 13.0), gFine);
    vec3 a = (side ? vec3(0.072, 0.07, 0.068) : vec3(0.05, 0.051, 0.054)) * (0.78 + 0.45 * n1) * (0.88 + 0.24 * grain);
    vec2 cs = side ? vec2(2.0, 1.4) : vec2(3.4, 2.1);
    vec2 cq = p / cs + seed * 3.0;
    vec2 cell = floor(cq); vec2 cl = fract(cq);
    vec2 lo = hash22(cell) * 0.3; vec2 hi = 1.0 - hash22(cell + 7.0) * 0.3;
    float inPatch = step(lo.x, cl.x) * step(cl.x, hi.x) * step(lo.y, cl.y) * step(cl.y, hi.y) * step(0.7, hash12(cell + 1.3));
    a = mix(a, a * (0.62 + 0.7 * hash12(cell + 3.1)), inPatch);
    float e = voronoiEdge(p * 0.5 + fbm3(p * 0.15) * 1.6);
    float crack = (1.0 - smoothstep(0.0, 0.04, e)) * smoothstep(0.45, 0.75, vnoise(p * 0.25)) * gFine;
    a *= 1.0 - crack * 0.55;
    float pot = side ? 0.0 : smoothstep(0.76, 0.8, vnoise(p * 0.35 + 11.0)) * smoothstep(0.5, 0.7, vnoise(p * 1.7));
    a = mix(a, vec3(0.03, 0.028, 0.026), pot);
    float puddle = smoothstep(0.58, 0.7, fbm3(p * 0.16 + 4.0) + pot * 0.5);
    float edgeMud = (side || vAux.x <= 0.0) ? 0.0 : smoothstep(vAux.x - 1.2, vAux.x - 0.1, abs(uv.y));
    a = mix(a, vec3(0.06, 0.05, 0.04), edgeMud * 0.6 * (0.5 + 0.5 * vnoise(p * 2.0)));
    if (!side && vAux.y > 0.5){
      float dash = step(0.5, fract(uv.x / 6.0));
      float lane = 0.0;
      for (int i = -1; i <= 1; i++){
        float lp = float(i) * vAux.x / 1.5;
        lane = max(lane, (1.0 - smoothstep(0.05, 0.08, abs(uv.y - lp))) * (i == 0 ? 1.0 : dash));
      }
      lane *= smoothstep(0.25, 0.6, vnoise(p * 1.3)) * 0.85 * aaf(uv * 4.0);
      a = mix(a, vec3(0.42, 0.42, 0.38), lane);
    }
    float leaves = smoothstep(0.7, 0.8, vnoise(p * 9.0 + 2.0)) * smoothstep(0.45, 0.8, fbm3(p * 0.35)) * (side ? 0.6 : edgeMud) * aaf(p * 9.0);
    a = mix(a, mix(vec3(0.07, 0.04, 0.018), vec3(0.13, 0.08, 0.03), vnoise(p * 23.0)), leaves);
    float wet = clamp(uWet * (0.55 + puddle * 0.9) + edgeMud * 0.3, 0.0, 1.0);
    a *= 1.0 - wet * 0.35;
    s.alb = a;
    s.spec = wet * (0.25 + puddle * 0.75) * (1.0 - leaves);
    s.gloss = 0.4 + puddle * 0.6;
    if (uSnowCover > 0.0){
      float sn = side ? smoothstep(0.35, 0.65, fbm3(p * 0.5)) : edgeMud * smoothstep(0.3, 0.6, fbm3(p * 0.7));
      sn = max(sn, side ? 0.0 : 0.5 * smoothstep(0.4, 0.6, vnoise(p * 1.1)) * (1.0 - smoothstep(0.3, 0.7, abs(abs(uv.y) - vAux.x * 0.45))));
      sn *= uSnowCover;
      s.alb = mix(s.alb, side ? vec3(0.72, 0.74, 0.78) : vec3(0.42, 0.42, 0.43), sn);
      s.spec *= 1.0 - sn;
    }
  } else if (mat == 6){
    // piatră cubică: 10 cm granite setts in rows
    vec2 p = wp.xz / 0.105;
    float row = floor(p.y);
    p.x += mod(row, 2.0) * 0.5 + hash12(vec2(row, 3.0)) * 0.3;
    vec2 c = floor(p); vec2 f = fract(p) - 0.5;
    vec2 j = (hash22(c) - 0.5) * 0.1;
    vec2 dd = abs(f - j);
    float aaC = aaf(p);
    float stone = mix(0.82, 1.0 - smoothstep(0.34, 0.47, max(dd.x, dd.y)), aaC);
    vec3 a = mix(vec3(0.075, 0.072, 0.072), mix(vec3(0.07, 0.068, 0.07), vec3(0.15, 0.14, 0.13), hash12(c)), aaC) * (0.85 + 0.3 * vnoise(wp.xz * 2.0));
    vec3 jc = mix(vec3(0.035, 0.03, 0.025), vec3(0.6, 0.62, 0.66), uSnowCover * smoothstep(0.3, 0.6, fbm3(wp.xz * 0.4)));
    s.alb = mix(jc, a, stone);
    vec2 gq = (f - j) * stone * aaC;
    s.n = normalize(s.n + vec3(gq.x, 0.0, gq.y) * 1.1);
    float wet = uWet * 0.8;
    s.alb *= 1.0 - wet * 0.3;
    s.spec = wet * 0.5 * stone; s.gloss = 0.55;
  } else if (mat == 8){
    vec2 p = wp.xz;
    float g1 = fbm(p * 0.25);
    vec3 grass = mix(vec3(0.085, 0.08, 0.055), vec3(0.13, 0.12, 0.075), vnoise(p * 4.0));
    float mudM = smoothstep(0.5, 0.65, g1);
    vec3 a = mix(grass, vec3(0.055, 0.045, 0.035), mudM);
    float leaves = smoothstep(0.62, 0.74, vnoise(p * 6.0 + 5.0)) * aaf(p * 6.0);
    a = mix(a, mix(vec3(0.08, 0.045, 0.02), vec3(0.14, 0.085, 0.035), vnoise(p * 19.0)), leaves * 0.7);
    a *= 0.85 + 0.3 * vnoise(p * 9.0) * gFine;
    s.alb = a;
    s.spec = mudM * uWet * 0.4; s.gloss = 0.3;
    s.alb = mix(s.alb, vec3(0.76, 0.79, 0.83), smoothstep(0.35, 0.6, g1 + uSnowCover * 0.6 - 0.25) * uSnowCover);
    s.wrap = 0.35;
  } else if (mat == 9){
    float chip = smoothstep(0.86, 0.9, vnoise(uv * 16.0 + seed * 7.0)) * gFine;
    float rust = smoothstep(0.7, 0.95, vnoise(vec2(uv.x * 7.0, uv.y * 0.9) + seed * 3.0)) * 0.4;
    s.alb = s.alb * (0.85 + 0.2 * vnoise(uv * 3.0));
    s.alb = mix(s.alb, vec3(0.2, 0.2, 0.19), chip * 0.7);
    s.alb = mix(s.alb, vec3(0.16, 0.07, 0.03), rust * (indoor ? 0.3 : 1.0));
    s.spec = 0.12 * (1.0 - chip); s.gloss = 0.4;
  } else if (mat == 10){
    float plank = fract(uv.y / 0.14);
    float gap = (1.0 - smoothstep(0.0, 0.08, min(plank, 1.0 - plank))) * gFine * aaf(uv * 7.0);
    float grain = vnoise(vec2(uv.x * 1.5, uv.y * 30.0) + seed * 4.0);
    s.alb *= (0.8 + 0.3 * grain) * (0.85 + 0.3 * hash12(vec2(floor(uv.y / 0.14), seed)));
    s.alb *= 1.0 - gap * 0.55;
    if (!indoor) s.alb = mix(s.alb, vec3(0.13, 0.11, 0.09), smoothstep(0.7, 0.78, vnoise(uv * vec2(3.0, 12.0) + seed)) * 0.6);
    else { s.spec = 0.18; s.gloss = 0.6; }
  } else if (mat == 11 || mat == 45){
    if (mat == 11){
      vec2 q = vec2(uv.x / 0.21, uv.y / 0.16);
      q.x += mod(floor(q.y), 2.0) * 0.5;
      vec2 f = fract(q);
      s.alb *= (0.65 + 0.35 * sin(f.x * 3.14159)) * (0.8 + 0.35 * hash12(floor(q)));
      s.alb *= 1.0 - (1.0 - smoothstep(0.0, 0.15, f.y)) * 0.45 * gFine;
      s.alb = mix(s.alb, vec3(0.12, 0.12, 0.08), smoothstep(0.6, 0.85, vnoise(uv * 0.8)) * 0.6);
    } else {
      float cor = sin(uv.x / 0.076 * 3.14159);
      s.n = normalize(s.n + cross(s.n, vec3(0.0, 1.0, 0.0)) * cor * 0.25 * gFine);
      float rust = smoothstep(0.35, 0.8, fbm3(uv * vec2(0.6, 0.3) + seed));
      s.alb = mix(s.alb, vec3(0.2, 0.08, 0.03), rust * 0.8);
      s.spec = 0.15 * (1.0 - rust); s.gloss = 0.5;
    }
    s.snowable = 1.0;
  } else if (mat == 12){
    s.alb *= 0.8 + 0.3 * fbm3(uv * 0.3);
    s.snowable = 1.0;
  } else if (mat == 15){
    // the pale, unfaded rectangle where a portrait hung
    s.alb = vec3(0.62, 0.6, 0.52) * (0.92 + 0.08 * vnoise(uv * 30.0));
  } else if (mat == 16){
    vec3 R = reflect(gRd, s.n);
    float fres = 0.04 + 0.5 * pow(1.0 - abs(dot(gRd, s.n)), 5.0);
    float dust = smoothstep(0.3, 0.8, fbm3(wp.xz * 1.5 + wp.y * 2.0)) * 0.3;
    float mud = indoor ? 0.0 : (1.0 - smoothstep(0.15, 0.55, wp.y - floor(wp.y / 100.0) * 100.0)) * 0.7;
    s.alb = mix(s.alb, vec3(0.1, 0.085, 0.07), mud);
    s.alb = mix(s.alb, s.alb * 0.8 + vec3(0.05), dust);
    s.spec = fres * (1.0 - mud) * (1.0 - dust) * 1.4; s.gloss = 0.85;
    s.snowable = indoor ? 0.0 : 1.0;
  } else if (mat == 17){
    vec3 R = reflect(gRd, s.n);
    float fres = 0.12 + 0.6 * pow(1.0 - abs(dot(gRd, s.n)), 4.0);
    vec3 inside = vec3(0.012, 0.012, 0.014) + uAmbSky * 0.03;
    // indoors, glass (vitrines, jars, the siphon) reflects the room, not the sky
    vec3 env = indoor ? (uAmbSky * 0.25 + vec3(0.25, 0.18, 0.1) * roomLit * 0.4) * (0.6 + 0.4 * vnoise(R.xz * 3.0 + R.y)) : reflectEnv(R);
    outCol = mix(inside + vCol * 0.2, env, fres) + vnoise(uv * 8.0) * 0.015;
    outCol += uLightCol * pow(max(dot(R, uLightDir), 0.0), 200.0) * getShadow(wp, s.n) * 3.0;
    done = true;
  } else if (mat == 18){
    s.alb = s.alb * 0.4 + vec3(0.06);
    s.emis = reflectEnv(reflect(gRd, s.n)) * (indoor ? 0.2 : 0.55);
    s.spec = 0.3; s.gloss = 0.95;
  } else if (mat == 19){
    s.alb = vec3(0.025, 0.025, 0.027) * (0.8 + 0.4 * vnoise(uv * 20.0));
  } else if (mat == 20){
    vec2 p = vec2(uv.x * 6.0, uv.y * 1.2);
    float pl = step(0.5, vAux.y);
    float flake = smoothstep(0.45, 0.6, fbm3(p * 1.4 + seed * 9.0));
    vec3 plane = mix(vec3(0.24, 0.24, 0.17), vec3(0.42, 0.42, 0.33), flake);
    vec3 dark = vec3(0.07, 0.06, 0.05) * (0.7 + 0.6 * smoothstep(0.3, 0.7, vnoise(vec2(uv.x * 22.0, uv.y * 2.0))));
    s.alb = mix(dark, plane, pl);
    float wash = (1.0 - smoothstep(1.1, 1.16, vLp.y)) * step(0.35, hash12(vec2(seed, 2.0)));
    s.alb = mix(s.alb, vec3(0.6, 0.6, 0.56) * (0.8 + 0.2 * vnoise(uv * 30.0)), wash);
    s.snowable = 0.6;
  } else if (mat == 22){
    // wallpaper: stripes, small flowers or a damask lozenge, picked by the room
    float k = floor(seed * 8.0);
    vec2 q = uv;
    float pat;
    if (mod(k, 3.0) < 1.0) pat = step(0.5, fract(q.x * 5.0)) * 0.08 + smoothstep(0.82, 0.9, vnoise(q * 14.0)) * 0.1;
    else if (mod(k, 3.0) < 2.0) { vec2 f = fract(q * vec2(6.0, 5.0)) - 0.5; pat = (1.0 - smoothstep(0.12, 0.2, length(f))) * 0.2; }
    else { vec2 f = abs(fract(q * vec2(4.0, 3.0)) - 0.5); pat = (1.0 - smoothstep(0.0, 0.05, abs(f.x + f.y - 0.35))) * 0.18; }
    s.alb *= (1.0 - pat * aaf(q * 6.0)) * (0.9 + 0.1 * vnoise(q * 3.0));
    // dirt and wear low down, a faded band where the furniture stood
    s.alb *= mix(0.88, 1.0, smoothstep(0.0, 0.9, uv.y));
    s.wrap = 0.4;
  } else if (mat == 23){
    s.alb = vec3(0.09, 0.06, 0.045);
    s.spec = smoothstep(0.85, 0.95, s.n.y) * 0.9; s.gloss = 0.9;
  } else if (mat == 24){
    vec2 p = wp.xz / 0.06;
    s.alb = mix(vec3(0.08, 0.075, 0.07), vec3(0.2, 0.19, 0.17), hash12(floor(p))) * (0.8 + 0.4 * vnoise(wp.xz * 2.0));
    s.alb = mix(s.alb * 0.6 + vCol * 0.5, s.alb, 0.5);
    s.alb = mix(vec3(0.12), s.alb, gFine * aaf(p));
  } else if (mat == 26){
    // tricolour with the socialist coat of arms cut out of the yellow band
    float u = uv.x / max(vAux.x, 0.01);
    vec2 hd = (vec2(u, uv.y) - 0.5) * vec2(vAux.x, 1.0);
    if (length(hd * vec2(1.0, 0.85)) < 0.19) discard;
    s.alb = (u < 0.333 ? vec3(0.02, 0.07, 0.36) : (u < 0.666 ? vec3(0.78, 0.55, 0.04) : vec3(0.55, 0.03, 0.03))) * (0.85 + 0.15 * vnoise(uv * 8.0));
    s.wrap = 0.6;
  } else if (mat == 27 || mat == 46){
    s.alb *= (0.92 + 0.08 * step(0.5, fract(uv.x * 6.0 + seed))) * (0.85 + 0.15 * vnoise(uv * 12.0));
    s.wrap = 0.6;
  } else if (mat == 28){
    s.alb *= 0.82 + 0.3 * fbm3(uv * 1.3 + seed * 4.0);
    s.alb *= mix(0.92 + 0.12 * vnoise(uv * 18.0), 1.0, 1.0 - gFine);
    if (!indoor) s.alb *= mix(0.72, 1.0, smoothstep(0.0, 0.9, wp.y));
    s.spec = uWet * 0.15 * (indoor ? 0.0 : 1.0);
  } else if (mat == 30 || mat == 56){
    // wool coats, upholstery and padded leatherette
    s.alb *= (0.8 + 0.35 * vnoise(vec2(uv.x * 6.0, uv.y * 0.9) + seed * 5.0)) * mix(1.0, 0.92 + 0.12 * vnoise(uv * 90.0), gFine);
    if (mat == 56) s.alb *= 0.9 + 0.12 * step(0.5, fract(uv.x * 8.0)) * step(0.5, fract(uv.y * 8.0));
    s.wrap = 0.45;
  } else if (mat == 37){
    s.alb *= 0.9 + 0.1 * vnoise(uv * 40.0);
    s.wrap = 0.5;
  } else if (mat == 44){
    // lamp glass: glows when switched on (and at night in the street)
    s.alb = mix(vec3(0.4, 0.42, 0.42), vCol * 0.55, 0.6);
    s.emis = vCol * vAux.x * (indoor ? smoothstep(0.0, 0.35, uWinLit) : uNight);
    s.spec = 0.3; s.gloss = 0.8;
  } else if (mat == 48){
    // parquet: strips or herringbone, varnished
    vec2 q = wp.xz;
    float hb = vAux.x;
    vec2 f;
    float id;
    if (hb < 0.5){ f = vec2(fract(q.x / 0.07), fract(q.y / 0.5 + floor(q.x / 0.07) * 0.37)); id = floor(q.x / 0.07) * 13.0 + floor(q.y / 0.5 + floor(q.x / 0.07) * 0.37); }
    else { vec2 r2 = vec2(q.x + q.y, q.x - q.y) * 0.7071; float c = floor(r2.x / 0.28); float o = mod(c, 2.0); f = vec2(fract(r2.x / 0.28), fract((r2.y + o * 0.14) / 0.07)); id = c * 7.0 + floor((r2.y + o * 0.14) / 0.07); }
    float joint = (1.0 - smoothstep(0.0, 0.06, min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y)))) * aaf(q * 14.0);
    s.alb *= (0.75 + 0.4 * hash12(vec2(id, seed))) * (0.85 + 0.25 * vnoise(vec2(q.x * 30.0, q.y * 3.0)));
    s.alb = mix(s.alb, s.alb * 0.5, joint * 0.7);
    s.spec = 0.35; s.gloss = 0.7;
  } else if (mat == 49 || mat == 51){
    // ceramic tiles: 15 cm square floor tiles in two tones, or glazed wall tiles
    float sz = mat == 49 ? 0.2 : 0.15;
    vec2 q = (mat == 49 ? wp.xz : uv) / sz;
    vec2 f = fract(q);
    float grout = (1.0 - smoothstep(0.0, 0.05, min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y)))) * aaf(q);
    float chk = mat == 49 && vAux.x < 0.5 ? mod(floor(q.x) + floor(q.y), 2.0) : 0.0;
    s.alb *= (0.92 + 0.12 * hash12(floor(q) + seed)) * mix(1.0, 0.72, chk);
    s.alb = mix(s.alb, vec3(0.35, 0.34, 0.32), grout * 0.7);
    s.spec = 0.45; s.gloss = 0.85;
  } else if (mat == 50){
    // terrazzo: chips of marble in grey cement, polished by a million footsteps
    // project on whichever plane the surface faces, so risers don't streak
    vec3 an = abs(s.n);
    vec2 base2 = an.y > 0.5 ? wp.xz : (an.x > an.z ? wp.zy : wp.xy);
    vec2 q = base2 * 22.0;
    float chips = smoothstep(0.55, 0.62, vnoise(q)) * 0.25 + smoothstep(0.7, 0.75, vnoise(q * 1.7 + 3.0)) * 0.2;
    s.alb *= (0.85 + 0.2 * vnoise(base2 * 1.5)) * (1.0 + chips * aaf(q) - 0.1 * (1.0 - aaf(q)));
    s.alb = mix(s.alb, s.alb * vec3(1.15, 1.05, 0.9), smoothstep(0.7, 0.75, vnoise(q * 0.8 + 9.0)) * 0.5 * aaf(q));
    s.spec = 0.3; s.gloss = 0.7;
  } else if (mat == 52){
    // gloss oil paint (the dado of every stairwell and kitchen), scuffed low down
    s.alb *= 0.9 + 0.12 * vnoise(uv * vec2(2.0, 0.5) + seed * 3.0);
    s.alb *= 1.0 - smoothstep(0.8, 0.95, vnoise(uv * vec2(14.0, 3.0) + seed)) * 0.12 * (1.0 - smoothstep(0.2, 1.0, uv.y));
    s.spec = 0.3; s.gloss = 0.6;
  } else if (mat == 53){
    // a woven carpet: border, field and a medallion
    vec2 sz = max(vAux, vec2(0.5));
    vec2 c = fract(uv / sz + 0.5) - 0.5;
    vec2 a2 = abs(c);
    float border = step(0.42, max(a2.x * sz.x / sz.y, a2.y));
    float med = 1.0 - smoothstep(0.12, 0.16, a2.x + a2.y * 1.2);
    float motif = step(0.5, fract((uv.x + uv.y) * 6.0)) * step(0.5, fract((uv.x - uv.y) * 6.0));
    vec3 field = s.alb, bc = s.alb * vec3(0.4, 0.45, 0.6) + vec3(0.06, 0.05, 0.03);
    s.alb = mix(field * (0.85 + 0.2 * motif * aaf(uv * 12.0)), bc, max(border, med * 0.8));
    s.alb *= 0.85 + 0.25 * vnoise(uv * 60.0);
    s.wrap = 0.5;
  } else if (mat == 54){
    // a television screen: grey glass when off, the flickering broadcast when on
    vec3 R = reflect(gRd, s.n);
    float fres = 0.06 + 0.5 * pow(1.0 - abs(dot(gRd, s.n)), 4.0);
    vec3 base = vec3(0.025, 0.028, 0.026);
    if (vAux.x > 0.5){
      float scan = 0.85 + 0.15 * sin(uv.y * 900.0 + uTime * 30.0);
      float blocks = vnoise(vec2(uv.x * 9.0, uv.y * 7.0 + floor(uTime * 1.5) * 3.1));
      base += tvLight(seed) * (0.6 + 0.6 * blocks) * scan * 1.6;
    }
    outCol = mix(base, reflectEnv(R) * 0.25, fres);
    done = true;
  } else if (mat == 55){
    // linoleum: marbled, worn
    s.alb *= 0.85 + 0.25 * fbm3(wp.xz * 2.0 + seed * 5.0);
    s.spec = 0.25; s.gloss = 0.5;
  } else if (mat == 57){
    // lace: crocheted doilies and net curtains
    vec2 q = uv * 40.0;
    float holes = smoothstep(0.25, 0.4, length(fract(q) - 0.5)) * aaf(q);
    s.alb *= 0.8 + 0.25 * holes;
    s.wrap = 0.7;
  } else {
    s.alb *= 0.88 + 0.22 * fbm3(wp.xz * 0.7 + wp.y * 0.9 + seed * 3.0);
  }

  if (!done){
    if (s.snowable > 0.0 && uSnowCover > 0.0){
      float nz = vnoise(wp.xz * 3.1 + wp.y * 2.3) * 0.7 + vnoise(wp.xz * 11.0) * 0.3;
      float sm = smoothstep(0.62, 0.86, s.n.y + (nz - 0.5) * 0.45) * s.snowable * uSnowCover;
      s.alb = mix(s.alb, vec3(0.78, 0.8, 0.84), sm);
      s.spec *= 1.0 - sm;
    }
    float sh = getShadow(wp, s.n);
    vec3 c;
    if (indoor){
      // inside: the sky reaches in weakly through the windows; at night the bulb is on in lit rooms
      float ndl = dot(s.n, uLightDir);
      float diff = clamp((ndl + s.wrap) / (1.0 + s.wrap), 0.0, 1.0);
      vec3 amb = mix(uAmbGround, uAmbSky, s.n.y * 0.5 + 0.5) * 0.85 * s.ao;
      vec3 bulb = vec3(1.0, 0.72, 0.42) * roomLit * (0.12 + 0.6 * smoothstep(0.0, 0.4, uWinLit)) * (0.75 + 0.25 * s.n.y);
      c = s.alb * (uLightCol * diff * sh + amb + bulb + vec3(0.012, 0.013, 0.016));
    } else c = lighting(s.alb, s.n, wp, sh, s.ao, s.wrap);
    if (s.spec > 0.0){
      vec3 R = reflect(gRd, s.n);
      float fres = 0.04 + 0.96 * pow(1.0 - max(dot(-gRd, s.n), 0.0), 5.0);
      vec3 env = indoor ? (uAmbSky * 0.2 + vec3(1.0, 0.72, 0.42) * roomLit * 0.3 * uWinLit) : reflectEnv(R);
      c += env * s.spec * mix(0.3, 1.0, fres) * s.gloss;
      c += uLightCol * pow(max(dot(R, uLightDir), 0.0), mix(8.0, 200.0, s.gloss)) * sh * s.spec * 1.5;
      c += localLights(R, wp) * s.spec * 0.15;
    }
    outCol = c + s.emis;
  }
  outCol = applyFog(outCol, wp);
  gl_FragColor = vec4(tonemap(outCol), 1.0);
}
`;

export interface WorldMats { opaque: THREE.ShaderMaterial; hideable: THREE.ShaderMaterial; instanced: THREE.ShaderMaterial; furniture: THREE.ShaderMaterial; glass: THREE.ShaderMaterial; depth: THREE.ShaderMaterial; depthHide: THREE.ShaderMaterial }

const GLASS_FS = /* glsl */`
varying vec3 vWp; varying vec3 vN; varying float vSeed;
void main(){
  vec3 rd = normalize(vWp - uCamPos);
  vec3 n = normalize(vN); if (!gl_FrontFacing) n = -n;
  vec3 R = reflect(rd, n);
  float fres = 0.06 + 0.6 * pow(1.0 - abs(dot(rd, n)), 4.0);
  vec3 s = skyGradient(normalize(vec3(R.x, max(R.y, 0.02), R.z)));
  vec3 refl = mix(uAmbSky * 0.35 + uAmbGround * 0.25, s, smoothstep(0.02, 0.4, R.y));
  float dirt = vnoise(vWp.xy * 6.0 + vWp.zy * 6.0) * 0.06;
  vec3 c = refl * 0.85 + uLightCol * pow(max(dot(R, uLightDir), 0.0), 220.0) * 2.0;
  float a = clamp(fres + dirt + 0.04, 0.0, 0.9);
  gl_FragColor = vec4(tonemap(applyFog(c, vWp)), a);
}`;
const GLASS_VS = /* glsl */`
attribute float aSeed;
varying vec3 vWp; varying vec3 vN; varying float vSeed;
void main(){ vec4 wp = modelMatrix * vec4(position, 1.0); vWp = wp.xyz; vN = normalize(mat3(modelMatrix) * normal); vSeed = aSeed; gl_Position = projectionMatrix * viewMatrix * wp; }`;

const DEPTH_VS = /* glsl */`
#ifdef HIDEABLE
attribute float aBid;
uniform sampler2D uHide;
#endif
void main(){
  vec4 p = vec4(position, 1.0);
#ifdef USE_INSTANCING
  p = instanceMatrix * p;
#endif
  gl_Position = projectionMatrix * viewMatrix * modelMatrix * p;
#ifdef HIDEABLE
  if (aBid >= 0.0) { int bi = int(aBid + 0.5); if (texelFetch(uHide, ivec2(bi % 1024, bi / 1024), 0).r > 0.5) gl_Position = vec4(2.0, 2.0, 2.0, 1.0); }
#endif
}`;

export function createWorldMaterials(): WorldMats {
  const opaque = makeMat(WORLD_VS, WORLD_FS, {}, { side: THREE.FrontSide });
  const hideable = makeMat(WORLD_VS, WORLD_FS, {}, { side: THREE.FrontSide, defines: { HIDEABLE: 1 } });
  const instanced = makeMat(WORLD_VS, WORLD_FS, {}, { side: THREE.FrontSide });
  const furniture = makeMat(WORLD_VS, WORLD_FS, {}, { side: THREE.FrontSide, defines: { INST_ATTR: 1 } });
  const glass = makeMat(GLASS_VS, GLASS_FS, {}, { transparent: true, depthWrite: false, side: THREE.DoubleSide });
  const depth = makeMat(DEPTH_VS, `void main(){ gl_FragColor = vec4(1.0); }`, {}, { side: THREE.DoubleSide });
  const depthHide = makeMat(DEPTH_VS, `void main(){ gl_FragColor = vec4(1.0); }`, {}, { side: THREE.DoubleSide, defines: { HIDEABLE: 1 } });
  return { opaque, hideable, instanced, furniture, glass, depth, depthHide };
}
