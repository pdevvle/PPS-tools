// ===================================================================
// Pantelimon, 1989 — engine slice. Wires the streamer, renderer, crowd,
// player and HUD together and runs the frame loop.
// ===================================================================
import * as THREE from 'three';
import type { CityData, CityRoad } from './data/schema';
import { U } from './render/uniforms';
import { createWorldMaterials } from './render/world';
import { createSky } from './render/sky';
import { createPost } from './render/post';
import { Environment, WEATHER, type WeatherKey } from './render/env';
import { ModelPool } from './world/pools';
import { buildProp, LAMP_HEAD } from './mesh/props';
import { drawItem } from './mesh/furniture';
import { Collider } from './world/collide';
import { Streamer } from './world/stream';
import { Player } from './world/player';
import { Crowd } from './crowd/crowd';
import { Street } from './crowd/agents';
import { GeoBuilder, A } from './mesh/builder';
import { M } from './mesh/mat';
import { toGeometry } from './render/geometry';
import { exteriorSteps } from './world/extras';
import { planBuilding } from './gen/plan';
import { City } from './gen/city';
import { Hud } from './hud';
import { DoorManager } from './world/doorman';

const $ = (id: string) => document.getElementById(id)!;
const params = new URLSearchParams(location.search);
const DEBUG = params.has('debug');

async function main() {
  const canvas = $('view') as HTMLCanvasElement;
  let renderer: THREE.WebGLRenderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance', stencil: false }); }
  catch { $('err').hidden = false; return; }
  renderer.autoClear = true;
  const hud = new Hud();
  hud.status('Se încarcă harta… (OpenStreetMap, ajustată la 1989)');
  const data = (await (await fetch(`${import.meta.env.BASE_URL}data/city.json`)).json()) as CityData;

  // ---------------- scene
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(70, 1, 0.08, 3000);
  const mats = createWorldMaterials();
  const sky = createSky();
  scene.add(sky.mesh);
  const env = new Environment(sky.mat);
  const post = createPost();
  const props = new ModelPool(buildProp, mats.instanced, mats.depth, true, false);
  const furniture = new ModelPool((b, key) => {
    const [type, v, on, lit, w, h] = key.split(':');
    drawItem(b, { type, x: 0, y: 0, z: 0, rot: 0, variant: +v, on: on === '1', w: w !== undefined ? +w : undefined, h: h !== undefined ? +h : undefined }, { lit: lit === '1' } as never, null);
  }, mats.furniture, mats.depth, false, true);
  scene.add(props.group, furniture.group);
  const crowd = new Crowd(4096);
  scene.add(crowd.group);
  const col = new Collider(data);
  const worker = await startWorker();
  const doors = new DoorManager(mats.furniture);
  scene.add(doors.group);
  const stream = new Streamer(worker, data, mats, props, furniture, col, crowd, doors);
  scene.add(stream.root);
  // the boys' football
  const ballB = new GeoBuilder(256);
  ballB.lathe(Array.from({ length: 9 }, (_, i) => { const a = -Math.PI / 2 + (i / 8) * Math.PI; return [Math.cos(a) * 0.11, Math.sin(a) * 0.11] as [number, number]; }), 10, A('#5a4028', M.WOOD, { seed: 0.4 }));
  const ball = new THREE.Mesh(toGeometry(ballB.finish()), mats.opaque);
  ball.userData = { depthMat: mats.depth, cast: true };
  scene.add(ball);

  // ---------------- where we start: outside a block near Șoseaua Pantelimon, on the morning of the 22nd
  const city = new City(data);
  const street = new Street(data);
  const start = pickStart(data, city);
  const player = new Player();
  player.x = start.x; player.z = start.z; player.y = 0.15; player.yaw = start.yaw;
  street.stage({ x: start.x, z: start.z, yaw: start.yaw + Math.PI }, start.window);
  crowd.set('street', street.agents());
  const sidewalkOff = (r: CityRoad) => r.width / 2 + (r.kind === 'primary' || r.kind === 'secondary' ? 1.7 : 1.1);

  // ---------------- shadows
  const SHADOW = 2048, HALF = 62;
  const shadowRT = new THREE.WebGLRenderTarget(SHADOW, SHADOW, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
  shadowRT.depthTexture = new THREE.DepthTexture(SHADOW, SHADOW);
  shadowRT.depthTexture.type = THREE.UnsignedIntType;
  U.uShadowMap.value = shadowRT.depthTexture;
  U.uShadowTexel.value = 1 / SHADOW;
  const lightCam = new THREE.OrthographicCamera(-HALF, HALF, HALF, -HALF, 1, 600);
  const bias = new THREE.Matrix4().set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1);
  const casters: THREE.Mesh[] = [], others: THREE.Object3D[] = [];
  function shadowPass() {
    const ld = U.uLightDir.value;
    if (ld.y < 0.02 || U.uShadowStrength.value < 0.01) return;
    // snap the box to shadow texels so edges don't crawl as you walk
    const texel = (HALF * 2) / SHADOW;
    const centre = new THREE.Vector3(camera.position.x, 0, camera.position.z).addScaledVector(new THREE.Vector3(-Math.sin(player.yaw), 0, -Math.cos(player.yaw)), HALF * 0.45);
    lightCam.position.copy(centre).addScaledVector(ld, 250);
    lightCam.lookAt(centre);
    lightCam.updateMatrixWorld();
    const v = new THREE.Vector3().copy(centre).applyMatrix4(lightCam.matrixWorldInverse);
    v.x = Math.round(v.x / texel) * texel; v.y = Math.round(v.y / texel) * texel;
    const back = v.applyMatrix4(lightCam.matrixWorld);
    lightCam.position.add(back.sub(centre));
    lightCam.updateMatrixWorld();
    lightCam.updateProjectionMatrix();
    U.uShadowMatrix.value.copy(bias).multiply(lightCam.projectionMatrix).multiply(lightCam.matrixWorldInverse);
    casters.length = 0; others.length = 0;
    const saved = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
    scene.traverseVisible((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      if (m.userData.cast) { saved.set(m, m.material); m.material = (m.userData.depthMat as THREE.Material) || mats.depth; }
      else { others.push(m); }
    });
    for (const o of others) o.visible = false;
    renderer.setRenderTarget(shadowRT);
    renderer.render(scene, lightCam);
    for (const o of others) o.visible = true;
    for (const [m, mt] of saved) m.material = mt;
  }

  // ---------------- render targets and post
  let sceneRT: THREE.WebGLRenderTarget | null = null;
  let scale = Math.min(window.devicePixelRatio || 1, 1.5);
  function resize() {
    const w = Math.max(1, Math.floor(innerWidth * scale)), h = Math.max(1, Math.floor(innerHeight * scale));
    renderer.setPixelRatio(1);
    renderer.setSize(innerWidth, innerHeight, false);
    canvas.width = w; canvas.height = h;
    renderer.setViewport(0, 0, w, h);
    sceneRT?.dispose();
    sceneRT = new THREE.WebGLRenderTarget(w, h, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter });
    sceneRT.depthTexture = new THREE.DepthTexture(w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    post.mat.uniforms.uTexel.value.set(1 / w, 1 / h);
    post.mat.uniforms.uAspect.value = w / h;
  }
  addEventListener('resize', resize);
  resize();

  // ---------------- input
  const keys = new Set<string>();
  let locked = false;
  addEventListener('keydown', (e) => {
    keys.add(e.code);
    if (e.code === 'KeyT') hours = (hours + 1) % 24;
    if (e.code === 'KeyG') hours = (hours + 23) % 24;
    if (e.code === 'KeyY') { const ks = Object.keys(WEATHER) as WeatherKey[]; weather = ks[(ks.indexOf(weather) + 1) % ks.length]; hud.toast(WEATHER[weather].label); }
    if (e.code === 'KeyP') { post.mat.uniforms.uPaint.value = post.mat.uniforms.uPaint.value > 0 ? 0 : 1; }
    if (e.code === 'KeyH') hud.toggleHelp();
    if (e.code === 'KeyE') doors.toggle();
  });
  addEventListener('keyup', (e) => keys.delete(e.code));
  canvas.addEventListener('click', () => { if (!locked) canvas.requestPointerLock?.(); });
  document.addEventListener('pointerlockchange', () => { locked = document.pointerLockElement === canvas; hud.locked(locked); });
  addEventListener('mousemove', (e) => {
    if (!locked) return;
    player.yaw -= e.movementX * 0.0022;
    player.pitch = Math.max(-1.45, Math.min(1.45, player.pitch - e.movementY * 0.0022));
  });

  // ---------------- state
  let hours = +(params.get('h') || 11.6);
  let weather: WeatherKey = (params.get('w') as WeatherKey) || 'clear';
  let last = performance.now(), time = 0, fpsAcc = 0, fpsN = 0, fps = 0;
  const lamps: THREE.Vector3[] = [];
  const dir = new THREE.Vector3();
  let manual = false;

  function lampLights() {
    // the nearest street lamps become point lights after dark
    lamps.length = 0;
    const e = props.entries;
    for (const [key, ent] of e) {
      if (!key.startsWith('lamppost:0')) continue;
      for (const l of ent.owners.values()) for (const it of l) lamps.push(new THREE.Vector3(...LAMP_HEAD).applyMatrix4(it.m));
    }
    const p = camera.position;
    lamps.sort((a, b) => a.distanceToSquared(p) - b.distanceToSquared(p));
    const on = env.night > 0.05;
    for (let i = 0; i < 8; i++) {
      const L = lamps[i];
      if (L && on) { U.uPL.value[i].set(L.x, L.y, L.z, 24); U.uPLC.value[i].set(1.0, 0.62, 0.3).multiplyScalar(2.2 * env.night); }
      else U.uPL.value[i].set(0, 0, 0, 0);
    }
  }

  function frame(dt: number) {
    time += dt;
    U.uTime.value = time;
    hours = (hours + dt / 600) % 24; // ten minutes of a December day per real minute
    env.update(hours, dt, weather);
    post.mat.uniforms.uNightGrade.value = env.night;
    post.mat.uniforms.uSmog.value = env.smog;
    // player
    const inp = {
      fwd: (keys.has('KeyW') || keys.has('ArrowUp') ? 1 : 0) - (keys.has('KeyS') || keys.has('ArrowDown') ? 1 : 0),
      right: (keys.has('KeyD') || keys.has('ArrowRight') ? 1 : 0) - (keys.has('KeyA') || keys.has('ArrowLeft') ? 1 : 0),
      run: keys.has('ShiftLeft') || keys.has('ShiftRight'), jump: keys.has('Space'),
    };
    camera.getWorldDirection(dir);
    doors.update(dt, player.x, player.y, player.z, dir.x, dir.z);
    doors.segments(player.x, player.z, col.dynamic);
    player.step(inp, Math.min(dt, 0.05), col);
    const bobY = Math.sin(player.bob * 2) * 0.03 * Math.min(1, player.speed / 2);
    camera.position.set(player.x, player.y + player.eye + bobY, player.z);
    camera.rotation.set(player.pitch, player.yaw, 0, 'YXZ');
    camera.updateMatrixWorld();
    U.uCamPos.value.copy(camera.position);
    sky.mesh.position.copy(camera.position);
    U.uCloudOffset.value.x += dt * 0.004 * (0.3 + U.uWind.value * 3);
    // world
    stream.update(dt, camera.position);
    street.update(dt, time, player.x, player.z, sidewalkOff);
    ball.position.set(street.ball.x, street.ball.y, street.ball.z);
    ball.rotation.x += dt * 6;
    crowd.upload(player.x, player.z);
    lampLights();
    // render
    shadowPass();
    renderer.setRenderTarget(sceneRT);
    renderer.render(scene, camera);
    post.mat.uniforms.tColor.value = sceneRT!.texture;
    renderer.setRenderTarget(null);
    renderer.render(post.scene, post.cam);
    // HUD
    camera.getWorldDirection(dir);
    const who = crowd.pick(camera.position.x, camera.position.y, camera.position.z, dir.x, dir.y, dir.z);
    const where = stream.where(camera.position.x, camera.position.y, camera.position.z);
    const near = city.roadNear(player.x, player.z);
    hud.update({
      hours, weather: WEATHER[weather].label,
      place: where ? where.label : near && near.dist < 30 ? near.name || 'Pantelimon' : 'Pantelimon',
      room: where?.room || '', who, prompt: doors.prompt(),
      stats: DEBUG ? `${fps.toFixed(0)} fps · ${renderer.info.render.calls} draws · ${(renderer.info.render.triangles / 1000).toFixed(0)}k tris · tiles ${stream.stats().tiles} · near ${stream.stats().near} · floors ${stream.stats().floors} · q ${stream.stats().queue} · ${stream.lastMs} · people ${crowd.count} · furniture ${furniture.instances} in ${furniture.draws} draws` : '',
    });
    fpsAcc += dt; fpsN++;
    if (fpsAcc > 0.5) { fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0; }
  }
  function loop() {
    const now = performance.now();
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (!manual) frame(dt);
    requestAnimationFrame(loop);
  }
  stream.onReady = () => hud.status('');
  requestAnimationFrame(loop);

  // ---------------- hooks for automated tests and screenshots
  (window as unknown as { __p89: unknown }).__p89 = {
    manual(on: boolean) { manual = on; },
    step(n = 1, dt = 1 / 30) { for (let i = 0; i < n; i++) frame(dt); },
    teleport(x: number, y: number, z: number, yaw = player.yaw, pitch = 0) { player.x = x; player.y = y; player.z = z; player.yaw = yaw; player.pitch = pitch; player.vy = 0; },
    walk(fwd: number, right: number, seconds: number) { const k = new Set(keys); keys.clear(); if (fwd > 0) keys.add('KeyW'); if (fwd < 0) keys.add('KeyS'); if (right > 0) keys.add('KeyD'); if (right < 0) keys.add('KeyA'); for (let t = 0; t < seconds; t += 1 / 30) frame(1 / 30); keys.clear(); for (const q of k) keys.add(q); },
    setTime(h: number) { hours = h; },
    setWeather(w: WeatherKey) { weather = w; },
    player, stream, crowd, start, data, col, doors,
    stats() { return { ...stream.stats(), people: crowd.count, furniture: furniture.instances, furnitureDraws: furniture.draws, calls: renderer.info.render.calls, tris: renderer.info.render.triangles, player: { x: player.x, y: player.y, z: player.z } }; },
    entrance(bi: number) {
      const p = planBuilding(data.buildings[bi], city, { furnish: false });
      return { frame: p.frame, entrances: p.entrances, steps: exteriorSteps(p) };
    },
  };
}

/** The mesh worker, or the same code on the main thread where workers can't start (some sandboxed hosts). */
async function startWorker(): Promise<Worker> {
  try {
    const w = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
    const ok = await new Promise<boolean>((res) => {
      const t = setTimeout(() => res(false), 4000);
      w.onerror = () => { clearTimeout(t); res(false); };
      // a probe: the worker answers 'ready' to an empty city
      w.onmessage = () => { clearTimeout(t); res(true); };
      w.postMessage({ t: 'init', data: { roads: [], buildings: [], areas: [], trams: [], trees: [] } });
    });
    if (ok) { w.onmessage = null; w.onerror = null; return w; }
    w.terminate();
  } catch { /* fall through */ }
  const mod = await import('./worker');
  const fake = {
    onmessage: null as ((ev: MessageEvent) => void) | null,
    postMessage(m: unknown) { setTimeout(() => mod.handle(m as never, (r) => fake.onmessage?.({ data: r } as MessageEvent)), 0); },
    terminate() {},
  };
  return fake as unknown as Worker;
}

/** A block entrance near Șoseaua Pantelimon with a living-room window on the second storey above the street. */
function pickStart(data: CityData, city: City): { x: number; z: number; yaw: number; window: { x: number; y: number; z: number; yaw: number } | null } {
  const sp = data.roads.filter((r) => r.name === 'Șoseaua Pantelimon');
  const mid = sp.length ? sp[Math.floor(sp.length / 2)].pts[0] : [0, 0];
  const cands = data.buildings.map((b, bi) => ({ b, bi, d: Math.hypot(b.poly[0][0] - mid[0] - 60, b.poly[0][1] - mid[1] - 60) })).filter((c) => c.b.kind === 'block' && c.b.levels >= 4 && c.b.levels <= 10).sort((a, b) => a.d - b.d);
  for (const c of cands.slice(0, 12)) {
    const p = planBuilding(c.b, city);
    const e = p.entrances[0];
    if (!e) continue;
    const { cx, cz, angle } = p.frame, co = Math.cos(angle), si = Math.sin(angle);
    const W = (lx: number, lz: number) => [cx + lx * co + lz * si, cz - lx * si + lz * co];
    const out = { n: [0, -1], s: [0, 1], w: [-1, 0], e: [1, 0] }[e.side]!;
    const [x, z] = W(e.x + out[0] * 9 + (out[1] !== 0 ? 3 : 0), e.z + out[1] * 9 + (out[0] !== 0 ? 3 : 0));
    if (city.inBuilding(x, z, 1.0)) continue;
    // face the block, a little to one side of the door
    const [ex, ez] = W(e.x, e.z);
    const yaw = Math.atan2(-(ex - x), -(ez - z)) + 0.25;
    // the window: a living room on floor 1 on the entrance side
    let window = null;
    const room = p.rooms.find((r) => r.floor === 1 && (r.type === 'living' || r.type === 'bedroom') && r.openings.some((o) => o.exterior && o.kind === 'window' && o.side === e.side));
    if (room) {
      const o = room.openings.find((q) => q.exterior && q.kind === 'window' && q.side === e.side)!;
      const t = (o.t0 + o.t1) / 2;
      const R = room.rect;
      const [lx, lz] = e.side === 'n' ? [t, R.z0 + 0.15] : e.side === 's' ? [t, R.z1 - 0.15] : e.side === 'w' ? [R.x0 + 0.15, t] : [R.x1 - 0.15, t];
      const [wx, wz] = W(lx, lz);
      const ox = out[0] * co + out[1] * si, oz = -out[0] * si + out[1] * co;
      window = { x: wx, y: room.y, z: wz, yaw: Math.atan2(ox, oz) };
    }
    return { x, z, yaw, window };
  }
  return { x: mid[0], z: mid[1] + 12, yaw: 0, window: null };
}

main().catch((e) => { console.error(e); const el = document.getElementById('err'); if (el) { el.hidden = false; el.textContent = String(e); } });
