// ===================================================================
// Streaming. Three levels of detail, all built in the worker:
//   tile  (96 m)  ground, far building shells (one mesh per tile), props
//   near  (~40 m) a building's exterior with real openings and glass,
//                 plus interior-mapped plugs for every storey
//   floor         one storey's rooms, stairs, furniture and residents,
//                 for the storeys you are on or can see into
// A far shell is hidden on the GPU (uHide) while its near version is up.
// ===================================================================
import * as THREE from 'three';
import type { BuildingPlan, CityData, V2 } from '../data/schema';
import { TILE } from '../gen/city';
import { pointInPoly, distToSegment } from '../core/geom';
import type { FromWorker, ToWorker } from './protocol';
import { toGeometry } from '../render/geometry';
import type { WorldMats } from '../render/world';
import type { ModelPool } from './pools';
import type { Collider } from './collide';
import { PROP_RADIUS } from '../mesh/props';
import type { Crowd } from '../crowd/crowd';
import type { DoorManager } from './doorman';
import { doorsFromPlan } from './doors';
import { residentsOf } from '../crowd/agents';
import { U } from '../render/uniforms';

interface TileRec { key: string; meshes: THREE.Mesh[]; buildings: number[] }
interface NearRec { bi: number; plan: BuildingPlan; group: THREE.Group; plugs: THREE.Mesh[]; floors: Map<number, THREE.Mesh>; pending: Set<number>; matrix: THREE.Matrix4; lastWanted: number }
interface BInfo { cx: number; cz: number; r: number; poly: V2[] }

export interface StreamStats { tiles: number; near: number; floors: number; queue: number; lastMs: string }

export class Streamer {
  readonly root = new THREE.Group();
  tiles = new Map<string, TileRec>();
  near = new Map<number, NearRec>();
  private pendingTiles = new Set<string>();
  private pendingNear = new Set<number>();
  private queue: ToWorker[] = [];
  private busy = 0;
  private info: BInfo[];
  private hideTex: THREE.DataTexture;
  private hideData: Uint8Array;
  private t = 0;
  lastMs = '';
  ready = false;
  onReady: (() => void) | null = null;
  constructor(private worker: Worker, data: CityData, private mats: WorldMats, private props: ModelPool, private furniture: ModelPool, private col: Collider, private crowd: Crowd, private doors: DoorManager) {
    this.info = data.buildings.map((b) => {
      let cx = 0, cz = 0; for (const p of b.poly) { cx += p[0]; cz += p[1]; } cx /= b.poly.length; cz /= b.poly.length;
      let r = 0; for (const p of b.poly) r = Math.max(r, Math.hypot(p[0] - cx, p[1] - cz));
      return { cx, cz, r, poly: b.poly };
    });
    const rows = Math.ceil(data.buildings.length / 1024) || 1;
    this.hideData = new Uint8Array(1024 * rows);
    this.hideTex = new THREE.DataTexture(this.hideData, 1024, rows, THREE.RedFormat, THREE.UnsignedByteType);
    this.hideTex.needsUpdate = true;
    U.uHide.value = this.hideTex;
    for (const m of [mats.hideable, mats.depthHide]) m.uniforms.uHide = U.uHide;
    worker.onmessage = (ev: MessageEvent<FromWorker>) => this.receive(ev.data);
    worker.postMessage({ t: 'init', data } satisfies ToWorker);
  }
  private send(m: ToWorker) { this.queue.push(m); this.pump(); }
  private pump() {
    // keep two jobs in flight so the worker never idles between messages
    while (this.ready && this.busy < 2 && this.queue.length) { this.worker.postMessage(this.queue.shift()!); this.busy++; }
  }
  /** Distance from a point to a building's footprint (0 inside). */
  footDist(bi: number, x: number, z: number): number {
    const b = this.info[bi];
    if (Math.hypot(x - b.cx, z - b.cz) - b.r > 60) return 1e9;
    if (pointInPoly(x, z, b.poly)) return 0;
    let d = 1e9;
    for (let i = 0; i < b.poly.length; i++) { const p = b.poly[i], q = b.poly[(i + 1) % b.poly.length]; d = Math.min(d, distToSegment(x, z, p[0], p[1], q[0], q[1])); }
    return d;
  }
  /** The building you are standing in, if any. */
  inside(x: number, z: number): number {
    for (const bi of this.near.keys()) if (pointInPoly(x, z, this.info[bi].poly)) return bi;
    return -1;
  }

  update(dt: number, cam: THREE.Vector3) {
    this.t += dt;
    if (!this.ready || this.t < 0.2) return;
    this.t = 0;
    const ti = Math.floor(cam.x / TILE), tj = Math.floor(cam.z / TILE);
    // ---- tiles: load within 2 rings (nearest first), drop beyond 3
    const want: [string, number][] = [];
    for (let i = ti - 3; i <= ti + 3; i++) for (let j = tj - 3; j <= tj + 3; j++) {
      const d = Math.hypot((i + 0.5) * TILE - cam.x, (j + 0.5) * TILE - cam.z);
      if (d < TILE * 2.9) want.push([`${i},${j}`, d]);
    }
    want.sort((a, b) => a[1] - b[1]);
    for (const [k] of want) if (!this.tiles.has(k) && !this.pendingTiles.has(k)) { this.pendingTiles.add(k); this.send({ t: 'tile', key: k }); }
    for (const [k, rec] of this.tiles) {
      const [i, j] = k.split(',').map(Number);
      if (Math.hypot((i + 0.5) * TILE - cam.x, (j + 0.5) * TILE - cam.z) > TILE * 3.8) this.dropTile(rec);
    }
    // ---- near buildings: the closest few within 40 m (kept until 55 m)
    const cands: [number, number][] = [];
    for (let bi = 0; bi < this.info.length; bi++) {
      const d = this.footDist(bi, cam.x, cam.z);
      if (d < 55) cands.push([bi, d]);
    }
    cands.sort((a, b) => a[1] - b[1]);
    const keep = new Set(cands.filter(([, d], i) => d < 55 && i < 7).map(([bi]) => bi));
    for (const [bi, d] of cands.slice(0, 5)) if (d < 40 && !this.near.has(bi) && !this.pendingNear.has(bi)) { this.pendingNear.add(bi); this.send({ t: 'near', bi }); }
    for (const [bi, rec] of this.near) if (!keep.has(bi)) this.dropNear(rec);
    // ---- storeys: the ones you're on or can see into
    const inside = this.inside(cam.x, cam.z);
    for (const rec of this.near.values()) {
      const fy = rec.plan.floorY;
      const wanted = new Set<number>();
      const d = this.footDist(rec.bi, cam.x, cam.z);
      const feet = cam.y - 1.62;
      let cur = 0;
      for (let f = 0; f < fy.length; f++) if (fy[f] <= feet + 0.6) cur = f;
      if (rec.bi === inside) { for (const f of [cur - 1, cur, cur + 1]) if (f >= 0 && f < fy.length) wanted.add(f); }
      else if (d < 26) {
        const byDist = fy.map((y, f) => [f, Math.abs(y + 1.4 - cam.y)] as [number, number]).sort((a, b) => a[1] - b[1]);
        for (const [f, dy] of byDist.slice(0, d < 10 ? 3 : 2)) if (dy < 9) wanted.add(f);
      }
      for (const f of wanted) if (!rec.floors.has(f) && !rec.pending.has(f)) { rec.pending.add(f); this.send({ t: 'floor', bi: rec.bi, f }); }
      for (const [f, mesh] of rec.floors) if (!wanted.has(f) && !(rec.bi === inside && Math.abs(f - cur) <= 2)) this.dropFloor(rec, f, mesh);
      rec.plugs.forEach((p, f) => (p.visible = !rec.floors.has(f)));
    }
    this.props.flush();
    this.furniture.flush();
  }

  private receive(m: FromWorker) {
    if (m.t === 'ready') { this.ready = true; this.pump(); this.onReady?.(); return; }
    this.busy = Math.max(0, this.busy - 1);
    this.lastMs = `${m.t} ${m.ms.toFixed(0)}ms`;
    if (m.t === 'tile') {
      this.pendingTiles.delete(m.key);
      const ground = new THREE.Mesh(toGeometry(m.ground), this.mats.opaque);
      ground.userData = { cast: false };
      const shells = new THREE.Mesh(toGeometry(m.shells, true), this.mats.hideable);
      shells.userData = { depthMat: this.mats.depthHide, cast: true };
      shells.frustumCulled = true;
      this.root.add(ground, shells);
      const circles: { x: number; z: number; r: number }[] = [];
      const boxes: { cx: number; cz: number; hx: number; hz: number; c: number; s: number }[] = [];
      const mat = new THREE.Matrix4();
      for (const p of m.props) {
        this.props.add(m.key, p.key, mat.clone().fromArray(p.m));
        if (p.type === 'car') boxes.push({ cx: p.x, cz: p.z, hx: 2.25, hz: 0.88, c: Math.cos(p.rot), s: Math.sin(p.rot) });
        else circles.push({ x: p.x, z: p.z, r: PROP_RADIUS[p.type] ?? 0.3 });
      }
      this.col.addTile(m.key, m.heights, m.n, m.x0, m.z0, circles, boxes);
      this.tiles.set(m.key, { key: m.key, meshes: [ground, shells], buildings: m.buildings });
      this.props.flush();
    } else if (m.t === 'near') {
      this.pendingNear.delete(m.bi);
      const p = m.plan;
      const group = new THREE.Group();
      group.position.set(p.frame.cx, 0, p.frame.cz);
      group.rotation.y = p.frame.angle;
      group.updateMatrixWorld(true);
      const ext = new THREE.Mesh(toGeometry(m.exterior), this.mats.opaque);
      ext.userData = { depthMat: this.mats.depth, cast: true };
      const glass = new THREE.Mesh(toGeometry(m.glass), this.mats.glass);
      glass.userData = { cast: false };
      glass.renderOrder = 5;
      group.add(ext, glass);
      const plugs = m.plugs.map((pd) => { const q = new THREE.Mesh(toGeometry(pd), this.mats.opaque); q.userData = { cast: false }; group.add(q); return q; });
      this.root.add(group);
      this.near.set(m.bi, { bi: m.bi, plan: p, group, plugs, floors: new Map(), pending: new Set(), matrix: group.matrixWorld.clone(), lastWanted: 0 });
      this.setHidden(m.bi, true);
      this.col.addPlan(m.bi, p);
    } else if (m.t === 'floor') {
      const rec = this.near.get(m.bi);
      if (!rec) return;
      rec.pending.delete(m.f);
      const mesh = new THREE.Mesh(toGeometry(m.shell), this.mats.opaque);
      mesh.userData = { cast: false };
      rec.group.add(mesh);
      rec.floors.set(m.f, mesh);
      rec.plugs[m.f].visible = false;
      const owner = `${m.bi}:${m.f}`;
      for (const it of m.inst) this.furniture.add(owner, it.key, rec.matrix.clone().multiply(new THREE.Matrix4().fromArray(it.m)), it.lit ? 2 : 1);
      this.furniture.flush();
      this.crowd.set(owner, residentsOf(rec.plan, m.f));
      this.doors.add(owner, doorsFromPlan(rec.plan, m.f), rec.plan.frame);
    }
    this.pump();
  }
  private dropTile(rec: TileRec) {
    for (const m of rec.meshes) { this.root.remove(m); m.geometry.dispose(); }
    this.props.remove(rec.key);
    this.col.removeTile(rec.key);
    this.tiles.delete(rec.key);
  }
  private dropNear(rec: NearRec) {
    for (const [f, mesh] of rec.floors) this.dropFloor(rec, f, mesh);
    rec.group.traverse((o) => { if ((o as THREE.Mesh).geometry) (o as THREE.Mesh).geometry.dispose(); });
    this.root.remove(rec.group);
    this.near.delete(rec.bi);
    this.setHidden(rec.bi, false);
    this.col.removePlan(rec.bi);
  }
  private dropFloor(rec: NearRec, f: number, mesh: THREE.Mesh) {
    rec.group.remove(mesh);
    mesh.geometry.dispose();
    rec.floors.delete(f);
    const owner = `${rec.bi}:${f}`;
    this.furniture.remove(owner);
    this.crowd.remove(owner);
    this.doors.remove(owner);
    if (rec.plugs[f]) rec.plugs[f].visible = true;
  }
  private setHidden(bi: number, on: boolean) { this.hideData[bi] = on ? 255 : 0; this.hideTex.needsUpdate = true; }
  stats(): StreamStats {
    let floors = 0; for (const r of this.near.values()) floors += r.floors.size;
    return { tiles: this.tiles.size, near: this.near.size, floors, queue: this.queue.length + this.busy, lastMs: this.lastMs };
  }
  /** Which flat or room you are in: for the HUD. */
  where(x: number, y: number, z: number): { label: string; room: string } | null {
    const bi = this.inside(x, z);
    if (bi < 0) return null;
    const rec = this.near.get(bi)!;
    const p = rec.plan, { cx, cz, angle } = p.frame, c = Math.cos(angle), s = Math.sin(angle);
    const dx = x - cx, dz = z - cz, lx = dx * c - dz * s, lz = dx * s + dz * c;
    const feet = y - 1.62;
    const room = p.rooms.find((r) => lx >= r.rect.x0 - 0.1 && lx <= r.rect.x1 + 0.1 && lz >= r.rect.z0 - 0.1 && lz <= r.rect.z1 + 0.1 && feet >= r.y - 0.4 && feet < r.y + r.h - 0.3);
    if (!room) return { label: p.label, room: '' };
    const unit = p.units.find((u) => u.rooms.includes(room.id));
    return { label: unit ? unit.label + (unit.family ? ` · fam. ${unit.family}` : '') : p.label, room: room.type };
  }
}
