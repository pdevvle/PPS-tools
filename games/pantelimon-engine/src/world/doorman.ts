// ===================================================================
// Door animation. Every door on a loaded storey is an instance; it
// swings on a slightly springy hinge when you come near (or press E),
// and closes again a little after you've gone. A door blocks you while
// it is shut, and its leaf is solid while it swings.
// ===================================================================
import * as THREE from 'three';
import type { DoorSpec } from './doors';
import { buildDoor, doorKey } from '../mesh/doors';
import { GeoBuilder } from '../mesh/builder';
import { toGeometry } from '../render/geometry';
import type { Seg } from './walls';

interface Door {
  spec: DoorSpec; owner: string; key: string;
  hx: number; hz: number; y: number;                 // hinge, world
  cx: number; cz: number; ox: number; oz: number;     // shut and open directions, world
  mx: number; mz: number;                             // middle of the doorway, world
  theta: number; vel: number; target: number; hold: boolean; away: number;
  mesh: THREE.InstancedMesh | null; slot: number; dirty: boolean;
}
interface Frame { cx: number; cz: number; angle: number }

export class DoorManager {
  group = new THREE.Group();
  private doors: Door[] = [];
  private byKey = new Map<string, { mesh: THREE.InstancedMesh | null; cap: number; geo: THREE.BufferGeometry | null }>();
  private needLayout = false;
  private m4 = new THREE.Matrix4(); private q = new THREE.Quaternion(); private e = new THREE.Euler(); private v = new THREE.Vector3(); private s = new THREE.Vector3(1, 1, 1);
  target: Door | null = null;
  constructor(private mat: THREE.Material) {}

  add(owner: string, specs: DoorSpec[], f: Frame) {
    const c = Math.cos(f.angle), s = Math.sin(f.angle);
    const W = (x: number, z: number): [number, number] => [f.cx + x * c + z * s, f.cz - x * s + z * c];
    const D = (x: number, z: number): [number, number] => [x * c + z * s, -x * s + z * c];
    for (const spec of specs) {
      const [hx, hz] = W(spec.hinge[0], spec.hinge[2]);
      const [cx, cz] = D(spec.closed[0], spec.closed[1]), [ox, oz] = D(spec.open[0], spec.open[1]);
      this.doors.push({ spec, owner, key: doorKey(spec.kind, spec.w, spec.h), hx, hz, y: spec.hinge[1], cx, cz, ox, oz, mx: hx + cx * spec.w / 2, mz: hz + cz * spec.w / 2, theta: 0, vel: 0, target: 0, hold: false, away: 0, mesh: null, slot: 0, dirty: true });
    }
    this.needLayout = true;
  }
  remove(owner: string) {
    const n = this.doors.length;
    this.doors = this.doors.filter((d) => d.owner !== owner);
    if (this.doors.length !== n) this.needLayout = true;
  }
  get count() { return this.doors.length; }

  private layout() {
    this.needLayout = false;
    const groups = new Map<string, Door[]>();
    for (const d of this.doors) { let l = groups.get(d.key); if (!l) groups.set(d.key, (l = [])); l.push(d); }
    for (const [key, e] of this.byKey) if (!groups.has(key) && e.mesh) { e.mesh.count = 0; e.mesh.visible = false; }
    for (const [key, list] of groups) {
      let e = this.byKey.get(key);
      if (!e) this.byKey.set(key, (e = { mesh: null, cap: 0, geo: null }));
      if (!e.mesh || list.length > e.cap) {
        if (!e.geo) { const b = new GeoBuilder(512); buildDoor(b, key); e.geo = toGeometry(b.finish()); }
        if (e.mesh) { this.group.remove(e.mesh); e.mesh.dispose(); }
        e.cap = Math.max(8, Math.ceil(list.length * 1.5));
        e.geo.setAttribute('aInst', new THREE.InstancedBufferAttribute(new Float32Array(e.cap * 2), 2));
        e.mesh = new THREE.InstancedMesh(e.geo, this.mat, e.cap);
        e.mesh.frustumCulled = false;
        e.mesh.userData = { cast: false };
        this.group.add(e.mesh);
      }
      const ia = e.mesh.geometry.getAttribute('aInst') as THREE.InstancedBufferAttribute;
      list.forEach((d, i) => {
        d.mesh = e!.mesh; d.slot = i; d.dirty = true;
        const indoor = d.spec.kind === 'inner' || d.spec.kind === 'front';
        ia.setXY(i, indoor ? (d.spec.lit ? 2 : 1) : 0, 0);
      });
      ia.needsUpdate = true;
      e.mesh.count = list.length;
      e.mesh.visible = true;
    }
  }

  private matrix(d: Door): THREE.Matrix4 {
    const sp = d.spec;
    if (sp.kind === 'garage') {
      // tilts up about a horizontal hinge at the top of the opening
      const phi = Math.atan2(-d.cz, d.cx);
      const lz = [Math.sin(phi), Math.cos(phi)];
      const sgn = lz[0] * d.ox + lz[1] * d.oz > 0 ? -1 : 1;
      const top = new THREE.Matrix4().makeTranslation(d.hx, d.y + sp.h, d.hz);
      const ry = new THREE.Matrix4().makeRotationY(phi);
      const rx = new THREE.Matrix4().makeRotationX(sgn * d.theta);
      const down = new THREE.Matrix4().makeTranslation(0, -sp.h, 0);
      return this.m4.copy(top).multiply(ry).multiply(rx).multiply(down);
    }
    const c = Math.cos(d.theta), s = Math.sin(d.theta);
    const dx = d.cx * c + d.ox * s, dz = d.cz * c + d.oz * s;
    this.e.set(0, Math.atan2(-dz, dx), 0);
    this.q.setFromEuler(this.e);
    return this.m4.compose(this.v.set(d.hx, d.y, d.hz), this.q, this.s);
  }

  /** The door you're facing, within reach. */
  private aimed(px: number, feet: number, pz: number, lx: number, lz: number): Door | null {
    let best: Door | null = null, bd = 2.3;
    const ll = Math.hypot(lx, lz) || 1;
    for (const d of this.doors) {
      if (Math.abs(feet - d.y) > 1.2) continue;
      const dx = d.mx - px, dz = d.mz - pz, dist = Math.hypot(dx, dz);
      if (dist > bd || dist < 0.05) continue;
      if ((dx * lx + dz * lz) / (dist * ll) < 0.55) continue;
      bd = dist; best = d;
    }
    return best;
  }
  /** E: open or shut the door you're facing, and its other half. */
  toggle() {
    const d = this.target;
    if (!d) return;
    const open = d.target < 0.1;
    const pair = /\/e\d+[ab]$/.test(d.spec.id) ? d.spec.id.slice(0, -1) : null;
    for (const o of this.doors) if (o === d || (pair && o.owner === d.owner && o.spec.id.slice(0, -1) === pair)) {
      o.target = open ? o.spec.max : 0; o.hold = !open; o.away = 0;
    }
  }

  update(dt: number, px: number, feet: number, pz: number, lookX: number, lookZ: number) {
    if (this.needLayout) this.layout();
    this.target = this.aimed(px, feet, pz, lookX, lookZ);
    const k = 38, damp = 2 * Math.sqrt(k) * 0.72;
    const touched = new Set<THREE.InstancedMesh>();
    for (const d of this.doors) {
      const dist = Math.hypot(d.mx - px, d.mz - pz);
      const level = Math.abs(feet - d.y) < 1.3;
      if (level && dist < 1.45 && !d.hold) { d.target = d.spec.max; d.away = 0; }
      else if (dist > 2.6 || !level) { d.away += dt; if (d.away > 2.5 && d.target > 0) { d.target = 0; } if (d.away > 2.5) d.hold = false; }
      if (Math.abs(d.target - d.theta) > 1e-3 || Math.abs(d.vel) > 1e-3) {
        // a springy hinge: a little overshoot, then it settles
        const acc = k * (d.target - d.theta) - damp * d.vel;
        d.vel += acc * Math.min(dt, 0.05);
        d.theta += d.vel * Math.min(dt, 0.05);
        if (d.theta < 0) { d.theta = 0; d.vel = -d.vel * 0.25; }  // stops against the frame
        if (d.theta > d.spec.max + 0.08) { d.theta = d.spec.max + 0.08; d.vel = 0; }
        d.dirty = true;
      }
      if (d.dirty && d.mesh) { d.mesh.setMatrixAt(d.slot, this.matrix(d)); touched.add(d.mesh); d.dirty = false; }
    }
    for (const m of touched) m.instanceMatrix.needsUpdate = true;
  }

  /** Leaves near a point as wall segments (world coordinates). */
  segments(px: number, pz: number, out: Seg[] = []): Seg[] {
    out.length = 0;
    for (const d of this.doors) {
      if (Math.abs(d.mx - px) > 4 || Math.abs(d.mz - pz) > 4) continue;
      const sp = d.spec;
      if (sp.kind === 'garage') {
        if (d.theta < 0.7) out.push({ ax: d.hx, az: d.hz, bx: d.hx + d.cx * sp.w, bz: d.hz + d.cz * sp.w, y0: d.y, y1: d.y + sp.h });
        continue;
      }
      const c = Math.cos(d.theta), s = Math.sin(d.theta);
      const dx = d.cx * c + d.ox * s, dz = d.cz * c + d.oz * s;
      out.push({ ax: d.hx + dx * 0.04, az: d.hz + dz * 0.04, bx: d.hx + dx * sp.w, bz: d.hz + dz * sp.w, y0: d.y, y1: d.y + sp.h });
    }
    return out;
  }
  /** For the HUD. */
  prompt(): string {
    const d = this.target;
    if (!d) return '';
    return `E · ${d.target > 0.1 ? 'închide' : 'deschide'} ${d.spec.kind === 'front' ? 'uşa apartamentului' : d.spec.kind === 'garage' ? 'garajul' : d.spec.kind === 'lobby' ? 'uşa blocului' : 'uşa'}`;
  }
}
