// ===================================================================
// Residents: who lives in each flat and house, and what they're doing on
// the afternoon of 22 December 1989. Most are glued to the television,
// which has been broadcasting the revolution live since 12:50; some
// listen to Radio Free Europe; some flats are empty because everyone has
// gone into the centre.
// ===================================================================
import type { BuildingPlan, FurnitureItem, Outfit, Pose, Resident, Room, Unit } from '../data/schema';
import { rngFor, pick, weighted, chance, type Rng } from '../core/rng';
import { SURNAMES, MEN, WOMEN, BOYS, GIRLS, JOBS_F, JOBS_M } from './names';

const SKIN = ['#c99a7c', '#bf8f70', '#b48468', '#c69574', '#ad7c60', '#cfa182'];
const HAIR_YOUNG = ['#2a1d14', '#3a2614', '#1c1612', '#4a3420', '#5a4026'];
const HAIR_OLD = ['#8a8680', '#a8a49c', '#6e6a64', '#c4c0b8'];
const HOME_M = [['#2a3550', '#2a3550'], ['#5a4a3a', '#3a3632'], ['#d8d4cc', '#2c2c32'], ['#6a6658', '#3e3c38'], ['#3e4a5a', '#2a2a30']];
const HOME_F = [['#4a4860', '#4a4860'], ['#6a3a3a', '#6a3a3a'], ['#76674e', '#3e3832'], ['#5a6a7a', '#3a3a44'], ['#7a5a64', '#4a3a40']];
const KIDS = [['#22314c', '#26448a'], ['#8a2620', '#2a3a6a'], ['#3a5a3a', '#35353a'], ['#5a4a6a', '#26448a']];

type Member = { sex: 'f' | 'm'; age: number; role: string };
const HOUSEHOLDS: (readonly [Member[], number])[] = [
  [[{ sex: 'm', age: 38, role: 'tatăl' }, { sex: 'f', age: 35, role: 'mama' }, { sex: 'm', age: 11, role: 'fiul' }], 26],
  [[{ sex: 'm', age: 42, role: 'tatăl' }, { sex: 'f', age: 39, role: 'mama' }, { sex: 'f', age: 15, role: 'fiica' }, { sex: 'm', age: 9, role: 'fiul' }], 18],
  [[{ sex: 'm', age: 68, role: 'bunicul' }, { sex: 'f', age: 64, role: 'bunica' }], 15],
  [[{ sex: 'f', age: 72, role: 'pensionara' }], 9],
  [[{ sex: 'm', age: 45, role: 'tatăl' }, { sex: 'f', age: 41, role: 'mama' }, { sex: 'm', age: 17, role: 'fiul' }, { sex: 'f', age: 70, role: 'bunica' }], 12],
  [[{ sex: 'm', age: 27, role: 'soţul' }, { sex: 'f', age: 25, role: 'soţia' }], 8],
  [[{ sex: 'm', age: 33, role: 'tatăl' }, { sex: 'f', age: 31, role: 'mama' }, { sex: 'f', age: 6, role: 'fiica' }, { sex: 'm', age: 3, role: 'fiul' }], 8],
  [[{ sex: 'm', age: 58, role: 'chiriaşul' }], 4],
];

function outfitFor(r: Rng, m: Member): Outfit {
  const kid = m.age < 16, old = m.age >= 60;
  const [top, bottom] = kid ? pick(r, KIDS) : m.sex === 'm' ? pick(r, HOME_M) : pick(r, HOME_F);
  return {
    top, bottom, skin: pick(r, SKIN), hair: old ? pick(r, HAIR_OLD) : pick(r, HAIR_YOUNG),
    hat: m.sex === 'f' && old && chance(r, 0.6) ? 'scarf' : 'none',
    skirt: m.sex === 'f' && !kid && chance(r, 0.75),
  };
}

interface Spot { pose: Pose; what: string; x: number; y: number; z: number; rot: number; room: Room; tag: string }

/** Places a person could be, derived from the furniture. */
function spotsIn(rooms: Room[]): Spot[] {
  const out: Spot[] = [];
  const at = (it: FurnitureItem, lx: number, lz: number) => {
    const c = Math.cos(it.rot), s = Math.sin(it.rot);
    return [it.x + lx * c + lz * s, it.z - lx * s + lz * c];
  };
  for (const room of rooms) {
    for (const it of room.furniture) {
      if (it.type === 'sofa') for (const lx of [-0.55, 0.05, 0.6]) { const [x, z] = at(it, lx, 0.05); out.push({ pose: 'sit', what: 'se uită la televizor', x, y: room.y, z, rot: it.rot, room, tag: 'tv' }); }
      if (it.type === 'armchair') { const [x, z] = at(it, 0, 0.05); out.push({ pose: 'sit', what: 'ascultă Europa Liberă la radio', x, y: room.y, z, rot: it.rot, room, tag: 'radio' }); }
      if (it.type === 'stool' || it.type === 'chair') out.push({ pose: 'sit', what: room.type === 'kitchen' ? 'stă la masă în bucătărie' : 'stă pe scaun', x: it.x, y: room.y, z: it.z, rot: it.rot + Math.PI, room, tag: 'table' });
      if (it.type === 'stove') { const [x, z] = at(it, 0, 0.62); out.push({ pose: 'cook', what: 'găteşte', x, y: room.y, z, rot: it.rot + Math.PI, room, tag: 'stove' }); }
      if (it.type === 'bed2' || it.type === 'bed1') { const [x, z] = at(it, 0, 0.1); out.push({ pose: 'lie', what: 's-a culcat', x, y: room.y + it.type.length * 0, z, rot: it.rot, room, tag: 'bed' }); }
      if (it.type === 'phonetable') { const [x, z] = at(it, 0.0, 0.55); out.push({ pose: 'phone', what: 'vorbeşte la telefon', x, y: room.y, z, rot: it.rot + Math.PI, room, tag: 'phone' }); }
      if (it.type === 'shopcounter') { const [x, z] = at(it, -0.4, -0.75); out.push({ pose: 'stand', what: 'vinde la tejghea', x, y: room.y, z, rot: it.rot, room, tag: 'counter' }); }
      if (it.type === 'candlestand') { const [x, z] = at(it, 0, 0.7); out.push({ pose: 'stand', what: 'aprinde o lumânare', x, y: room.y, z, rot: it.rot + Math.PI, room, tag: 'candle' }); }
      if (it.type === 'teacherdesk' || it.type === 'desk' || it.type === 'workbench') { const [x, z] = at(it, 0, 0.65); out.push({ pose: 'stand', what: 'lucrează', x, y: room.y, z, rot: it.rot + Math.PI, room, tag: 'work' }); }
      if (it.type === 'car') { const [x, z] = at(it, 1.25, 1.0); out.push({ pose: 'stand', what: 'repară maşina', x, y: room.y, z, rot: it.rot - Math.PI / 2, room, tag: 'car' }); }
    }
    for (const o of room.openings) {
      if (o.kind !== 'window' || !o.exterior || o.y0 > 1.2) continue;
      const c = (o.t0 + o.t1) / 2, R = room.rect, d = 0.45;
      const [x, z, rot] = o.side === 'n' ? [c, R.z0 + d, Math.PI] : o.side === 's' ? [c, R.z1 - d, 0] : o.side === 'w' ? [R.x0 + d, c, -Math.PI / 2] : [R.x1 - d, c, Math.PI / 2];
      out.push({ pose: 'window', what: 'se uită pe fereastră', x, y: room.y, z, rot, room, tag: 'window' });
    }
  }
  return out;
}

function takeSpot(spots: Spot[], used: Set<Spot>, r: Rng, prefs: [string, number][]): Spot | null {
  const tag = weighted(r, prefs);
  const free = spots.filter((s) => !used.has(s) && s.tag === tag);
  const any = free.length ? free : spots.filter((s) => !used.has(s) && prefs.some(([t]) => t === s.tag));
  if (!any.length) return null;
  const s = pick(r, any);
  used.add(s);
  return s;
}

function populateHome(plan: BuildingPlan, u: Unit, roomsById: Map<string, Room>) {
  const r = rngFor('home', u.id);
  u.family = pick(r, SURNAMES);
  // a few flats are empty this afternoon: the family has gone into town (houses always have someone in)
  if (u.kind === 'flat' && chance(r, 0.08)) {
    const tvRoom = u.rooms.map((id) => roomsById.get(id)!).find((rm) => rm.type === 'living');
    const tv = tvRoom?.furniture.find((f) => f.type === 'tv');
    if (tv && chance(r, 0.5)) tv.on = true; // left on in the rush
    return;
  }
  const rooms = u.rooms.map((id) => roomsById.get(id)!).filter(Boolean);
  const spots = spotsIn(rooms);
  const used = new Set<Spot>();
  const all = weighted(r, HOUSEHOLDS);
  const members = all.filter((_, i) => i === 0 || chance(r, 0.86));
  members.forEach((m, i) => {
    const kid = m.age < 16, old = m.age >= 60;
    const prefs: [string, number][] = kid ? [['tv', 6], ['bed', 2], ['window', 3], ['table', 1]]
      : old ? [['tv', 4], ['radio', 3], ['bed', 2], ['window', 2], ['table', 1]]
      : m.sex === 'f' ? [['tv', 5], ['stove', 3], ['window', 2], ['phone', 1], ['table', 1]]
      : [['tv', 6], ['radio', 2], ['window', 2], ['table', 2], ['phone', 1]];
    const s = takeSpot(spots, used, r, prefs);
    if (!s) return;
    const first = m.sex === 'm' ? (kid ? pick(r, BOYS) : pick(r, MEN)) : kid ? pick(r, GIRLS) : pick(r, WOMEN);
    const res: Resident = {
      id: `${u.id}/p${i}`, name: `${first} ${u.family}`, age: m.age + Math.floor(r() * 5) - 2, sex: m.sex, role: m.role,
      occupation: kid ? (m.age < 7 ? 'preşcolar' : 'elev') : old ? (m.sex === 'm' ? 'pensionar' : 'pensionară') : m.sex === 'm' ? pick(r, JOBS_M) : pick(r, JOBS_F),
      outfit: outfitFor(r, m),
      activity: { pose: s.pose, what: s.what, x: +s.x.toFixed(3), y: s.y, z: +s.z.toFixed(3), rot: +s.rot.toFixed(4) },
    };
    u.household.push(res);
    s.room.lit = true;
    if (s.tag === 'tv') for (const it of s.room.furniture) if (it.type === 'tv') it.on = true;
    if (s.tag === 'radio') for (const it of s.room.furniture) if (it.type === 'radio') it.on = true;
  });
  // the television is on in most homes that have someone in
  for (const rm of rooms) for (const it of rm.furniture) if (it.type === 'tv' && u.household.length && chance(r, 0.7)) it.on = true;
  void plan;
}

function populatePublic(u: Unit, roomsById: Map<string, Room>) {
  const r = rngFor('staff', u.id);
  const rooms = u.rooms.map((id) => roomsById.get(id)!).filter(Boolean);
  const spots = spotsIn(rooms);
  const room = rooms[0];
  if (!room) return;
  const plans: [string, number, Member][] = room.type === 'shop' ? [['counter', 0.75, { sex: 'f', age: 40, role: 'vânzătoarea' }]]
    : room.type === 'nave' ? [['candle', 1, { sex: 'f', age: 70, role: 'credincioasa' }], ['candle', 0.7, { sex: 'f', age: 66, role: 'credincioasa' }]]
    : room.type === 'garage' ? [['car', 0.35, { sex: 'm', age: 50, role: 'proprietarul' }]]
    : room.type === 'workshop' ? [['work', 0.4, { sex: 'm', age: 55, role: 'paznicul' }]]
    : room.type === 'classroom' || room.type === 'office' ? [['work', 0.12, { sex: 'm', age: 60, role: 'portarul' }]] : [];
  const used = new Set<Spot>();
  plans.forEach(([tag, p, m], i) => {
    if (!chance(r, p)) return;
    const s = takeSpot(spots, used, r, [[tag, 1]]);
    if (!s) return;
    const first = m.sex === 'm' ? pick(r, MEN) : pick(r, WOMEN);
    u.household.push({
      id: `${u.id}/s${i}`, name: `${first} ${pick(r, SURNAMES)}`, age: m.age + Math.floor(r() * 9) - 4, sex: m.sex, role: m.role, occupation: m.role,
      outfit: outfitFor(r, m), activity: { pose: s.pose, what: s.what, x: +s.x.toFixed(3), y: s.y, z: +s.z.toFixed(3), rot: +s.rot.toFixed(4) },
    });
    s.room.lit = true;
  });
}

export function populatePlan(plan: BuildingPlan): void {
  const byId = new Map(plan.rooms.map((rm) => [rm.id, rm] as const));
  for (const u of plan.units) {
    if (u.kind === 'flat' || u.kind === 'house') populateHome(plan, u, byId);
    else populatePublic(u, byId);
  }
}
