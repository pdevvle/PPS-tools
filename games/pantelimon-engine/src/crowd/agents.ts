// ===================================================================
// Who is in the street and in the flats.
//   residents  — every household member the generators placed, posed at
//                the furniture they use (sofa, stove, bed, window...)
//   the march  — a column of workers walking west along Șoseaua
//                Pantelimon toward the centre on 22 December, chanting,
//                flags with the arms cut out
//   pedestrians — people on the pavements around you
//   the scene  — two boys with a ball, a woman shaking a rug out of a
//                second-storey window, a man with a newspaper and a cigarette
// ===================================================================
import type { BuildingPlan, CityData, CityRoad, Resident, V2 } from '../data/schema';
import { POSE, FLAG, type Agent } from './crowd';
import { rngFor, pick, chance, type Rng } from '../core/rng';

const s2l = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const lin = (hex: string): [number, number, number] => { const n = parseInt(hex.slice(1), 16); return [s2l(((n >> 16) & 255) / 255), s2l(((n >> 8) & 255) / 255), s2l((n & 255) / 255)]; };
const POSES: Record<string, number> = { stand: POSE.stand, walk: POSE.stand, sit: POSE.sit, lie: POSE.lie, window: POSE.window, cook: POSE.cook, chant: POSE.chant, phone: POSE.phone, read: POSE.read };

/** Residents of one storey, in world coordinates. */
export function residentsOf(plan: BuildingPlan, floor: number): Agent[] {
  const out: Agent[] = [];
  const { cx, cz, angle } = plan.frame;
  const c = Math.cos(angle), s = Math.sin(angle);
  for (const u of plan.units) {
    if (u.floor !== floor && !(u.kind === 'house')) continue;
    for (const r of u.household) {
      const a = r.activity;
      const room = plan.rooms.find((q) => Math.abs(q.y - a.y) < 0.1 && a.x >= q.rect.x0 - 0.1 && a.x <= q.rect.x1 + 0.1 && a.z >= q.rect.z0 - 0.1 && a.z <= q.rect.z1 + 0.1);
      if (!room || room.floor !== floor) continue;
      out.push(residentAgent(r, cx + a.x * c + a.z * s, a.y, cz - a.x * s + a.z * c, a.rot + angle, room.lit, `${u.label}`));
    }
  }
  return out;
}
function residentAgent(r: Resident, x: number, y: number, z: number, yaw: number, lit: boolean, where: string): Agent {
  const o = r.outfit;
  const hat = o.hat === 'scarf' ? 4 : 0; // no hats indoors, but grandmothers keep the basma on
  const kid = r.age < 14;
  return {
    x, y, z, yaw, pose: POSES[r.activity.pose] ?? 0, phase: 0, speed: 0, scale: kid ? 0.55 + r.age * 0.032 : r.sex === 'f' ? 0.95 : 1.0,
    top: lin(o.top), hat, bottom: lin(o.bottom), flags: (o.skirt ? FLAG.skirt : 0) | FLAG.indoor | (lit ? FLAG.lit : 0),
    skin: lin(o.skin), hairStyle: r.sex === 'f' ? (r.age > 50 ? 2 : 1) : 0, hair: lin(o.hair),
    name: r.name, info: `${r.age} ani · ${r.occupation} · ${where}`, what: r.activity.what,
    fem: r.sex === 'f', age: Math.min(1, r.age / 80),
  };
}

// ---------------------------------------------------------------- street clothes of December 1989
const COATS_M = ['#2a2724', '#3a342c', '#2c3038', '#4a4034', '#33302a', '#45403a', '#2e2a26', '#3e3a30'];
const COATS_F = ['#4a3a32', '#5a4a3e', '#3a3236', '#6a5a48', '#2e2c30', '#5a3a30', '#7a6a58', '#42383a'];
const TROUSERS = ['#22201e', '#2a2a2c', '#302a24', '#28241f', '#1e1e22'];
const SKIN = ['#c8a088', '#b89078', '#d4ac94', '#a88068', '#c09880'];
const HAIR = ['#2a2018', '#3a2a1c', '#1a1612', '#4a3a2a', '#6a6460', '#8a8480'];
const NAMES_M = ['Ion', 'Gheorghe', 'Vasile', 'Constantin', 'Nicolae', 'Mihai', 'Dumitru', 'Petre', 'Marin', 'Florin', 'Costel', 'Viorel'];
const NAMES_F = ['Maria', 'Elena', 'Ioana', 'Ana', 'Florica', 'Gabriela', 'Rodica', 'Mariana', 'Viorica', 'Doina'];
const SURN = ['Popescu', 'Ionescu', 'Constantinescu', 'Dumitrescu', 'Stan', 'Gheorghe', 'Marin', 'Radu', 'Dinu', 'Matei', 'Niculescu', 'Stoica'];
const WORK = ['strungar la IMGB', 'lăcătuş la Faur', 'şofer la ITB', 'muncitor la Granitul', 'electrician', 'zidar', 'student', 'inginer la Electroaparataj', 'vânzătoare', 'ţesătoare la Postăvăria Română'];
const CHANTS = ['„Jos Ceauşescu!"', '„Ole, ole, ole, Ceauşescu nu mai e!"', '„Libertate!"', '„Armata e cu noi!"', '„Fără violenţă!"', '„Noi suntem poporul!"'];

function streetPerson(r: Rng, kind: 'march' | 'walk', idx: number): Agent {
  const f = chance(r, kind === 'march' ? 0.3 : 0.48);
  const age = 18 + Math.floor(r() * 50);
  const hat = f ? (chance(r, 0.45) ? 4 : chance(r, 0.4) ? 2 : chance(r, 0.4) ? 3 : 0) : chance(r, 0.4) ? 2 : chance(r, 0.4) ? 1 : chance(r, 0.4) ? 3 : 0;
  const top = lin(f ? pick(r, COATS_F) : pick(r, COATS_M));
  const flags = (f && chance(r, 0.7) ? FLAG.skirt : 0) | (chance(r, 0.65) ? FLAG.coat : 0);
  const first = f ? pick(r, NAMES_F) : pick(r, NAMES_M);
  return {
    x: 0, y: 0, z: 0, yaw: 0, pose: kind === 'march' ? (chance(r, 0.35) ? POSE.chant : POSE.walk) : POSE.walk, phase: r() * 6.28, speed: 0, scale: f ? 0.94 + r() * 0.05 : 0.98 + r() * 0.06,
    top, hat, bottom: f && flags & FLAG.skirt ? lin(pick(r, COATS_F)) : lin(pick(r, TROUSERS)), flags,
    skin: lin(pick(r, SKIN)), hairStyle: f ? (chance(r, 0.5) ? 1 : 2) : 0, hair: lin(age > 55 ? pick(r, HAIR.slice(4)) : pick(r, HAIR.slice(0, 4))),
    fem: f, age: age / 80,
    name: `${first} ${pick(r, SURN)}`, info: `${age} ani · ${age < 25 && chance(r, 0.5) ? "student" : age > 62 ? (f ? "pensionară" : "pensionar") : pick(r, WORK.filter((w) => w !== "student"))}`, what: kind === 'march' ? `strigă ${pick(r, CHANTS)}` : idx % 3 ? 'merge grăbit spre centru' : 'se uită după coloană',
  };
}

// ---------------------------------------------------------------- paths
interface Path { pts: V2[]; len: number[]; total: number }
function makePath(pts: V2[]): Path {
  const len = [0];
  for (let i = 1; i < pts.length; i++) len.push(len[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return { pts, len, total: len[len.length - 1] };
}
/** Point and direction a distance along a path, offset sideways (+ = left of travel). */
function along(p: Path, d: number, off: number): [number, number, number] {
  d = Math.max(0, Math.min(p.total - 1e-3, d));
  let i = 1;
  while (i < p.len.length - 1 && p.len[i] < d) i++;
  const a = p.pts[i - 1], b = p.pts[i], L = p.len[i] - p.len[i - 1] || 1, t = (d - p.len[i - 1]) / L;
  const ux = (b[0] - a[0]) / L, uz = (b[1] - a[1]) / L;
  return [a[0] + (b[0] - a[0]) * t - uz * off, a[1] + (b[1] - a[1]) * t + ux * off, Math.atan2(ux, uz)];
}
/** Chain the OSM ways of one street into a single line, west to east. */
function streetLine(roads: CityRoad[], name: string): V2[] {
  const ways = roads.filter((r) => r.name === name && r.kind !== 'path').map((r) => r.pts.slice());
  if (!ways.length) return [];
  ways.sort((a, b) => Math.min(a[0][0], a[a.length - 1][0]) - Math.min(b[0][0], b[b.length - 1][0]));
  const first = ways.shift()!;
  let line = first[0][0] <= first[first.length - 1][0] ? first : first.reverse();
  let guard = 0;
  while (ways.length && guard++ < 200) {
    const end = line[line.length - 1];
    let bi = -1, bd = 25, rev = false;
    ways.forEach((w, i) => {
      const d0 = Math.hypot(w[0][0] - end[0], w[0][1] - end[1]), d1 = Math.hypot(w[w.length - 1][0] - end[0], w[w.length - 1][1] - end[1]);
      if (d0 < bd && w[w.length - 1][0] > end[0] - 5) { bd = d0; bi = i; rev = false; }
      if (d1 < bd && w[0][0] > end[0] - 5) { bd = d1; bi = i; rev = true; }
    });
    if (bi < 0) break;
    const w = ways.splice(bi, 1)[0];
    line = line.concat(rev ? w.reverse() : w);
  }
  return line;
}

export class Street {
  march: { a: Agent; d: number; off: number; speed: number }[] = [];
  walkers: { a: Agent; p: Path; d: number; dir: number; off: number; speed: number }[] = [];
  scene: Agent[] = [];
  ball = { x: 0, y: 0.11, z: 0, t: 0 };
  private marchPath: Path | null = null;
  private roads: CityRoad[];
  private boys: Agent[] = [];
  private man: { a: Agent; p: Path; d: number } | null = null;
  constructor(data: CityData) {
    this.roads = data.roads.filter((r) => r.kind !== 'path' && r.kind !== 'service');
    const r = rngFor('street');
    const line = streetLine(data.roads, 'Șoseaua Pantelimon');
    if (line.length > 1) {
      // west is toward the centre: walk from the east end
      this.marchPath = makePath(line.slice().reverse());
      const rows = 26, perRow = 7;
      for (let i = 0; i < rows * perRow; i++) {
        const row = Math.floor(i / perRow), col = i % perRow;
        const a = streetPerson(r, 'march', i);
        if (col === 3 && row % 3 === 0) { a.pose = POSE.flag; a.flags |= FLAG.flag; a.what = 'poartă steagul cu stema decupată'; }
        this.march.push({ a, d: 60 + row * 1.6 + r() * 0.5, off: (col - (perRow - 1) / 2) * 0.95 + (r() - 0.5) * 0.3, speed: 1.15 + r() * 0.08 });
      }
    }
    for (let i = 0; i < 70; i++) this.walkers.push({ a: streetPerson(r, 'walk', i), p: makePath([[0, 0], [1, 0]]), d: 0, dir: 1, off: 0, speed: 1.0 + r() * 0.5 });
  }
  /** Set up the street scene of the original demo around a spot on a side street. */
  stage(home: { x: number; z: number; yaw: number }, window: { x: number; y: number; z: number; yaw: number } | null) {
    const r = rngFor('stage');
    const kid = (name: string, top: string, x: number, z: number, yaw: number): Agent => ({
      x, y: 0, z, yaw, pose: POSE.play, phase: 0, speed: 0, scale: 0.72, top: lin(top), hat: 3, bottom: lin('#2a2e3a'), flags: 0,
      skin: lin('#d0a890'), hairStyle: 0, hair: lin('#3a2a1c'), name, info: '11 ani · elev', what: 'joacă fotbal pe stradă',
    });
    const fx = Math.sin(home.yaw), fz = Math.cos(home.yaw);
    const ax = home.x + fx * 4 - fz * 3, az = home.z + fz * 4 + fx * 3;
    const bx = home.x + fx * 4 + fz * 3, bz = home.z + fz * 4 - fx * 3;
    this.boys = [kid('Costel Marin', '#7a2a22', ax, az, Math.atan2(bx - ax, bz - az)), kid('Sorin Dinu', '#2a4a6a', bx, bz, Math.atan2(ax - bx, az - bz))];
    this.scene = [...this.boys];
    if (window) {
      this.scene.push({
        x: window.x, y: window.y, z: window.z, yaw: window.yaw, pose: POSE.lean, phase: 0, speed: 0, scale: 0.95,
        top: lin('#6a4a5a'), hat: 4, bottom: lin('#4a3a3a'), flags: FLAG.skirt | FLAG.rug | FLAG.indoor | FLAG.lit,
        skin: lin('#c8a088'), hairStyle: 2, hair: lin('#3a2a1c'), name: 'Florica Stan', info: '58 ani · pensionară', what: 'scutură covorul pe fereastră',
      });
    }
    const near = this.nearestRoad(home.x, home.z);
    if (near) {
      const a = streetPerson(r, 'walk', 0);
      a.pose = POSE.readwalk; a.name = 'Petre Ionescu'; a.info = '52 ani · contabil'; a.what = 'citeşte „România Liberă" şi fumează o Carpaţi';
      a.hat = 1; a.flags = FLAG.coat; a.top = lin('#3e3a30');
      this.man = { a, p: makePath(near.pts), d: 0 };
      this.scene.push(a);
    }
  }
  private nearestRoad(x: number, z: number): CityRoad | null {
    let best: CityRoad | null = null, bd = 1e9;
    for (const r of this.roads) for (const p of r.pts) { const d = Math.hypot(p[0] - x, p[1] - z); if (d < bd) { bd = d; best = r; } }
    return best;
  }
  update(dt: number, t: number, cx: number, cz: number, sidewalkOff: (r: CityRoad) => number) {
    const MP = this.marchPath;
    if (MP) for (const m of this.march) {
      m.d += m.speed * dt;
      if (m.d > MP.total - 5) m.d -= MP.total - 70;
      const [x, z, yaw] = along(MP, m.d, m.off);
      m.a.x = x; m.a.z = z; m.a.yaw = yaw; m.a.speed = m.speed * 3.2; m.a.y = 0.02;
    }
    for (const w of this.walkers) {
      const dx = w.a.x - cx, dz = w.a.z - cz;
      if (w.p.total < 2 || dx * dx + dz * dz > 150 * 150) this.respawn(w, cx, cz, sidewalkOff);
      w.d += w.dir * w.speed * dt;
      if (w.d > w.p.total || w.d < 0) { w.dir = -w.dir; w.d = Math.max(0, Math.min(w.p.total, w.d)); }
      const [x, z, yaw] = along(w.p, w.d, w.off);
      w.a.x = x; w.a.z = z; w.a.yaw = w.dir > 0 ? yaw : yaw + Math.PI; w.a.speed = w.speed * 3.0; w.a.y = 0.15;
    }
    // the boys pass the ball; it rolls along the ground between them
    if (this.boys.length === 2) {
      const [A, B] = this.boys;
      const period = 3.2, k = (t % (period * 2)) / period;
      const from = k < 1 ? A : B, to = k < 1 ? B : A, u = k < 1 ? k : k - 1;
      const e = Math.min(1, u * 1.15);
      this.ball.x = from.x + (to.x - from.x) * e + Math.sin(from.yaw) * 0.35 * (1 - e);
      this.ball.z = from.z + (to.z - from.z) * e + Math.cos(from.yaw) * 0.35 * (1 - e);
      this.ball.y = 0.11 + Math.abs(Math.sin(e * Math.PI)) * 0.25 * (1 - e);
      // the kicker's leg swings at the start of each pass
      A.phase = k < 1 ? Math.PI * 0.5 - Math.min(1, u * 4) * Math.PI : -1.2;
      B.phase = k >= 1 ? Math.PI * 0.5 - Math.min(1, u * 4) * Math.PI : -1.2;
      A.speed = 0; B.speed = 0;
    }
    if (this.man) {
      const m = this.man;
      m.d += 1.05 * dt;
      if (m.d > m.p.total) m.d = 0;
      const [x, z, yaw] = along(m.p, m.d, -5.2);
      m.a.x = x; m.a.z = z; m.a.yaw = yaw; m.a.speed = 3.2; m.a.y = 0.15;
    }
  }
  private respawn(w: Street['walkers'][number], cx: number, cz: number, sidewalkOff: (r: CityRoad) => number) {
    const r = Math.random;
    for (let k = 0; k < 20; k++) {
      const road = this.roads[Math.floor(r() * this.roads.length)];
      const p = road.pts[Math.floor(r() * road.pts.length)];
      if (Math.hypot(p[0] - cx, p[1] - cz) > 110) continue;
      w.p = makePath(road.pts);
      w.d = r() * w.p.total;
      w.dir = r() < 0.5 ? 1 : -1;
      w.off = sidewalkOff(road) * (r() < 0.5 ? 1 : -1);
      return;
    }
  }
  agents(): Agent[] { return [...this.march.map((m) => m.a), ...this.walkers.map((w) => w.a), ...this.scene]; }
}
