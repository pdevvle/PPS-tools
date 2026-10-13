// ===================================================================
// The mesh worker: owns the city data, runs the generators and the
// meshers, and posts finished arrays back to the main thread.
// ===================================================================
import type { BuildingPlan } from './data/schema';
import { City } from './gen/city';
import { planBuilding } from './gen/plan';
import { GeoBuilder, transferables, type MeshData } from './mesh/builder';
import { buildExterior, buildFloor, buildPlugs } from './mesh/building';
import { buildGround } from './mesh/ground';
import type { FromWorker, PropInstance, ToWorker } from './world/protocol';

let city: City | null = null;
const plans = new Map<number, BuildingPlan>();
function plan(bi: number): BuildingPlan {
  let p = plans.get(bi);
  if (p) { plans.delete(bi); plans.set(bi, p); return p; }
  p = planBuilding(city!.data.buildings[bi], city!);
  plans.set(bi, p);
  if (plans.size > 160) plans.delete(plans.keys().next().value!);
  return p;
}
let post: (m: FromWorker, tr?: ArrayBuffer[]) => void = (m, tr = []) => (self as unknown as Worker).postMessage(m, tr);
const tx = (...ms: MeshData[]) => ms.flatMap(transferables);

/** Handle one message. Exported so the page can run this in-thread where workers are blocked. */
export function handle(m: ToWorker, reply?: (m: FromWorker) => void) {
  if (reply) post = (x) => reply(x);
  const t0 = performance.now();
  if (m.t === 'init') { city = new City(m.data); post({ t: 'ready' }); return; }
  if (!city) return;
  if (m.t === 'tile') {
    const g = new GeoBuilder(1 << 14);
    const gr = buildGround(city, m.key, g);
    const s = new GeoBuilder(1 << 15);
    const tile = city.tiles.get(m.key);
    const buildings = tile ? tile.buildings : [];
    for (const bi of buildings) {
      const p = plan(bi);
      s.bid = bi;
      s.push().translate(p.frame.cx, 0, p.frame.cz).rotateY(p.frame.angle);
      buildExterior(p, s, null, { near: false });
      s.pop();
    }
    const props: PropInstance[] = city.props(m.key).map((q) => {
      const c = Math.cos(q.rot), sn = Math.sin(q.rot), k = q.scale ?? 1;
      return { key: `${q.type}:${q.variant}`, type: q.type, x: q.x, z: q.z, rot: q.rot, m: [c * k, 0, -sn * k, 0, 0, k, 0, 0, sn * k, 0, c * k, 0, q.x, q.y, q.z, 1] };
    });
    const ground = g.finish(), shells = s.finish();
    post({ t: 'tile', key: m.key, ground, shells, heights: gr.heights, n: gr.n, x0: gr.x0, z0: gr.z0, props, buildings, ms: performance.now() - t0 }, [...tx(ground, shells), gr.heights.buffer as ArrayBuffer]);
    return;
  }
  if (m.t === 'near') {
    const p = plan(m.bi);
    const b = new GeoBuilder(1 << 15), g = new GeoBuilder(1 << 12);
    buildExterior(p, b, g, { near: true });
    const plugs = p.floorY.map((_, f) => { const q = new GeoBuilder(256); buildPlugs(p, f, q); return q.finish(); });
    const exterior = b.finish(), glass = g.finish();
    post({ t: 'near', bi: m.bi, plan: p, exterior, glass, plugs, ms: performance.now() - t0 }, tx(exterior, glass, ...plugs));
    return;
  }
  if (m.t === 'floor') {
    const p = plan(m.bi);
    const b = new GeoBuilder(1 << 15);
    const inst = buildFloor(p, m.f, b);
    const shell = b.finish();
    post({ t: 'floor', bi: m.bi, f: m.f, shell, inst, ms: performance.now() - t0 }, tx(shell));
  }
};

if (typeof (globalThis as { WorkerGlobalScope?: unknown }).WorkerGlobalScope !== 'undefined') self.onmessage = (ev: MessageEvent<ToWorker>) => handle(ev.data);
