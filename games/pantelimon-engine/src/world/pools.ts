// ===================================================================
// Instanced model pools. One InstancedMesh per model key, shared by
// every streamed chunk that uses the model; chunks add and remove their
// instances by owner id. Used for furniture (one draw per model, however
// many flats are loaded) and street props.
// ===================================================================
import * as THREE from 'three';
import { GeoBuilder, type MeshData } from '../mesh/builder';
import { toGeometry } from '../render/geometry';

interface Inst { m: THREE.Matrix4; a: number }
interface Entry { mesh: THREE.InstancedMesh | null; owners: Map<string, Inst[]>; dirty: boolean; cap: number; geo: THREE.BufferGeometry | null }

export class ModelPool {
  entries = new Map<string, Entry>();
  group = new THREE.Group();
  constructor(private build: (b: GeoBuilder, key: string) => void, private mat: THREE.Material, private depthMat: THREE.Material, private castShadow: boolean, private instAttr: boolean) {}
  private model(key: string): THREE.BufferGeometry {
    const b = new GeoBuilder(512);
    this.build(b, key);
    const md: MeshData = b.finish();
    return toGeometry(md);
  }
  add(owner: string, key: string, m: THREE.Matrix4, a = 0) {
    let e = this.entries.get(key);
    if (!e) this.entries.set(key, (e = { mesh: null, owners: new Map(), dirty: true, cap: 0, geo: null }));
    let l = e.owners.get(owner);
    if (!l) e.owners.set(owner, (l = []));
    l.push({ m, a });
    e.dirty = true;
  }
  remove(owner: string) {
    for (const e of this.entries.values()) if (e.owners.delete(owner)) e.dirty = true;
  }
  /** Rebuild the instance buffers of every key that changed. */
  flush() {
    for (const [key, e] of this.entries) {
      if (!e.dirty) continue;
      e.dirty = false;
      let n = 0;
      for (const l of e.owners.values()) n += l.length;
      if (n > e.cap || !e.mesh) {
        if (!e.geo) e.geo = this.model(key);
        if (e.mesh) { this.group.remove(e.mesh); e.mesh.dispose(); }
        e.cap = Math.max(8, Math.ceil(n * 1.5));
        const geo = e.geo;
        if (this.instAttr) geo.setAttribute('aInst', new THREE.InstancedBufferAttribute(new Float32Array(e.cap * 2), 2));
        e.mesh = new THREE.InstancedMesh(geo, this.mat, e.cap);
        e.mesh.frustumCulled = false;
        e.mesh.userData = { depthMat: this.depthMat, cast: this.castShadow };
        this.group.add(e.mesh);
      }
      const mesh = e.mesh!;
      const ia = this.instAttr ? (mesh.geometry.getAttribute('aInst') as THREE.InstancedBufferAttribute) : null;
      let i = 0;
      for (const l of e.owners.values()) for (const it of l) {
        mesh.setMatrixAt(i, it.m);
        if (ia) ia.setXY(i, it.a, 0);
        i++;
      }
      mesh.count = n;
      mesh.instanceMatrix.needsUpdate = true;
      if (ia) ia.needsUpdate = true;
      mesh.visible = n > 0;
    }
  }
  get instances() { let n = 0; for (const e of this.entries.values()) for (const l of e.owners.values()) n += l.length; return n; }
  get draws() { let n = 0; for (const e of this.entries.values()) if (e.mesh && e.mesh.count > 0) n++; return n; }
}
