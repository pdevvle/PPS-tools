// Run the generators headless (no browser, no three.js) to prove they port,
// check that every room can be reached, and optionally write the results as JSON.
// usage: npx tsx tools/bake.ts [--out baked] [--only <buildingId>]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { BuildingPlan, CityData, Room } from '../src/data/schema';
import { City } from '../src/gen/city';
import { planBuilding } from '../src/gen/plan';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const args = process.argv.slice(2);
const outDir = args.includes('--out') ? path.join(root, args[args.indexOf('--out') + 1] || 'baked') : null;
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;

const data = JSON.parse(fs.readFileSync(path.join(root, 'public/data/city.json'), 'utf8')) as CityData;
const city = new City(data);
const t0 = performance.now();
let rooms = 0, items = 0, people = 0, units = 0, unreachable = 0, flights = 0;
const problems: string[] = [];
const byType: Record<string, number> = {};
const plans: BuildingPlan[] = [];

/** Rooms reachable from the street through doors and stairs. */
function reachable(plan: BuildingPlan): Set<string> {
  const byId = new Map(plan.rooms.map((r) => [r.id, r] as const));
  const seen = new Set<string>();
  const queue: Room[] = plan.rooms.filter((r) => r.openings.some((o) => o.kind === 'entrance' && o.exterior));
  // stair cores join the floors of one section; house halls join through their flights
  const stairRooms = plan.rooms.filter((r) => r.type === 'stair' || r.type === 'lobby' || (r.type === 'hall' && plan.kind === 'house'));
  const sameCore = (a: Room, b: Room) => Math.abs(a.rect.x0 - b.rect.x0) < 0.2 && Math.abs(a.rect.z0 - b.rect.z0) < 0.2 && Math.abs(a.rect.x1 - b.rect.x1) < 0.2;
  while (queue.length) {
    const r = queue.pop()!;
    if (seen.has(r.id)) continue;
    seen.add(r.id);
    for (const o of r.openings) if (o.kind === 'door' && o.to && !seen.has(o.to)) queue.push(byId.get(o.to)!);
    if (stairRooms.includes(r)) for (const s of stairRooms) if (s !== r && sameCore(r, s) && !seen.has(s.id)) queue.push(s);
    // any flight that starts in this room leads to whichever room it arrives in
    for (const fl of plan.stairs) {
      const cx = (fl.x0 + fl.x1) / 2, cz = (fl.z0 + fl.z1) / 2;
      const inside = (q: Room) => cx > q.rect.x0 - 0.05 && cx < q.rect.x1 + 0.05 && cz > q.rect.z0 - 0.05 && cz < q.rect.z1 + 0.05;
      if (!inside(r)) continue;
      const other = Math.abs(r.y - fl.yA) < 0.05 ? fl.yB : Math.abs(r.y - fl.yB) < 0.05 ? fl.yA : null;
      if (other === null) continue;
      for (const q of plan.rooms) if (!seen.has(q.id) && Math.abs(q.y - other) < 0.05 && inside(q)) queue.push(q);
    }
  }
  return seen;
}

for (const b of data.buildings) {
  if (only && b.id !== only) continue;
  const plan = planBuilding(b, city);
  plans.push(plan);
  rooms += plan.rooms.length;
  units += plan.units.length;
  flights += plan.stairs.length;
  for (const r of plan.rooms) {
    items += r.furniture.length;
    byType[r.type] = (byType[r.type] || 0) + 1;
    if (r.rect.x1 - r.rect.x0 < 0.8 || r.rect.z1 - r.rect.z0 < 0.8) problems.push(`${b.id}: tiny room ${r.type} ${JSON.stringify(r.rect)}`);
    for (const f of r.furniture) {
      if (f.x < r.rect.x0 - 0.05 || f.x > r.rect.x1 + 0.05 || f.z < r.rect.z0 - 0.05 || f.z > r.rect.z1 + 0.05) problems.push(`${b.id}: ${f.type} outside ${r.type}`);
    }
  }
  for (const u of plan.units) people += u.household.length;
  const seen = reachable(plan);
  const lost = plan.rooms.filter((r) => !seen.has(r.id));
  unreachable += lost.length;
  if (lost.length && problems.length < 40) problems.push(`${b.id} (${b.kind}, ${b.levels}): ${lost.length}/${plan.rooms.length} rooms unreachable: ${[...new Set(lost.map((r) => r.type))].join(',')}`);
}
const ms = performance.now() - t0;
console.log(`${plans.length} buildings → ${units} units, ${rooms} rooms, ${flights} stair flights, ${items} furniture items, ${people} residents in ${ms.toFixed(0)} ms (${(ms / plans.length).toFixed(2)} ms per building)`);
console.log('rooms by type', byType);
console.log(`unreachable rooms: ${unreachable} (${((unreachable / rooms) * 100).toFixed(2)}%)`);
if (problems.length) console.log(problems.slice(0, 40).join('\n'));
if (outDir) {
  fs.mkdirSync(path.join(outDir, 'buildings'), { recursive: true });
  for (const p of plans) fs.writeFileSync(path.join(outDir, 'buildings', `${p.id}.json`), JSON.stringify(p));
  const tiles: Record<string, unknown> = {};
  for (const key of city.tiles.keys()) tiles[key] = { buildings: city.tiles.get(key)!.buildings.map((i) => data.buildings[i].id), props: city.props(key) };
  fs.writeFileSync(path.join(outDir, 'tiles.json'), JSON.stringify(tiles));
  console.log('wrote', outDir);
}
