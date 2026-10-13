// ===================================================================
// Building plans: footprint → wings → stair sections → flats → rooms,
// with every door and window placed once and shared by the interior and
// the facade. Pure data; no rendering.
// ===================================================================
import type { BuildingPlan, CityBuilding, Landing, Opening, Room, RoomType, Unit, Wing, RoadKind } from '../data/schema';
import { minAreaOBB, rectCover, toLocal, toWorld, type Rect } from '../core/geom';
import { rngFor, pick, chance, type Rng } from '../core/rng';
import { furnishPlan } from './furnish';
import { populatePlan } from './residents';

export interface RoadHit { dist: number; dx: number; dz: number; kind: RoadKind; name: string }
export interface PlanContext { roadNear(x: number, z: number): RoadHit | null }

export const SH = 2.75;      // storey height of the prefab blocks
const EXT = 0.3;             // exterior wall thickness
const INT = 0.12;            // interior partition thickness
const SLAB = 0.25;
type Side = 'n' | 's' | 'e' | 'w';

const PANEL = ['#a8a395', '#b0a892', '#9f9d96', '#aaa491', '#b9b3a6', '#aeaa9e', '#b5ae9c', '#bcb5a5', '#b2ad9f'];
const ACCENT = ['#b4a07a', '#8a5236', '#a69f90', '#7e4a34', '#8c5a3e', '#9a3a2a', '#a0998a'];
const FRAMES = ['#d6d1c4', '#cfc8b6', '#5a3f2c', '#e0dbcf'];

/** How a wing's canonical frame (u along the long side, v across with the front at low v) maps to building-local axes. */
export interface Frame { swap: boolean; flip: boolean }
const F0: Frame = { swap: false, flip: false };
function mapRect(c: Rect, T: Frame): Rect {
  const v0 = T.flip ? -c.z1 : c.z0, v1 = T.flip ? -c.z0 : c.z1;
  return T.swap ? { x0: v0, x1: v1, z0: c.x0, z1: c.x1 } : { x0: c.x0, x1: c.x1, z0: v0, z1: v1 };
}
function mapSide(s: Side, T: Frame): Side {
  const v = (a: Side) => (T.flip ? (a === 'n' ? 's' : a === 's' ? 'n' : a) : a);
  const c = v(s);
  if (!T.swap) return c;
  return c === 'n' ? 'w' : c === 's' ? 'e' : c === 'w' ? 'n' : 's';
}
/** Canonical coordinate along a side → local coordinate along the mapped side. */
function mapAlong(s: Side, a: number, T: Frame): number {
  const alongV = s === 'e' || s === 'w';
  return alongV && T.flip ? -a : a;
}

/** A layout session for one building: canonical frames, room creation, openings. */
class Layout {
  rooms: Room[] = [];
  units: Unit[] = [];
  private exteriorOf = new Map<string, Record<Side, boolean>>();
  private nextRoom = 0;
  constructor(public plan: BuildingPlan, public r: Rng) {}

  room(type: RoomType, floor: number, c: Rect, T: Frame = F0, h?: number): Room {
    const cell = mapRect(c, T);
    const ext = this.edgeExterior(cell);
    const rect = {
      x0: cell.x0 + (ext.w ? EXT : INT / 2), x1: cell.x1 - (ext.e ? EXT : INT / 2),
      z0: cell.z0 + (ext.n ? EXT : INT / 2), z1: cell.z1 - (ext.s ? EXT : INT / 2),
    };
    const p = this.plan;
    const y = p.floorY[floor];
    const top = floor + 1 < p.floorY.length ? p.floorY[floor + 1] : p.height;
    const room: Room = {
      id: `${p.id}/r${this.nextRoom++}`, type, floor, rect, y, h: h ?? Math.max(2.3, top - y - SLAB),
      openings: [], furniture: [], wallpaper: Math.floor(this.r() * 8), lit: false,
    };
    this.exteriorOf.set(room.id, ext);
    this.rooms.push(room);
    return room;
  }
  isExterior(room: Room, side: Side): boolean { return !!this.exteriorOf.get(room.id)?.[side]; }
  private edgeExterior(cell: Rect): Record<Side, boolean> {
    const W = this.plan.wings;
    const onEdge = (side: Side) => {
      const mx = (cell.x0 + cell.x1) / 2, mz = (cell.z0 + cell.z1) / 2;
      const [px, pz] = side === 'n' ? [mx, cell.z0 - 0.4] : side === 's' ? [mx, cell.z1 + 0.4] : side === 'w' ? [cell.x0 - 0.4, mz] : [cell.x1 + 0.4, mz];
      return !W.some((w) => px > w.x0 && px < w.x1 && pz > w.z0 && pz < w.z1);
    };
    return { n: onEdge('n'), s: onEdge('s'), e: onEdge('e'), w: onEdge('w') };
  }
  side(s: Side, T: Frame = F0): Side { return mapSide(s, T); }
  /** Opening centred at `along` on canonical side s. */
  open(room: Room, s: Side, along: number, width: number, y0: number, y1: number, kind: Opening['kind'], T: Frame = F0, exterior?: boolean): Opening | null {
    const side = mapSide(s, T);
    const a = mapAlong(s, along, T);
    const [lo, hi] = side === 'n' || side === 's' ? [room.rect.x0, room.rect.x1] : [room.rect.z0, room.rect.z1];
    const half = width / 2;
    if (hi - lo < width + 0.16) return null;
    const c = Math.min(Math.max(a, lo + half + 0.08), hi - half - 0.08);
    const o: Opening = { kind, side, t0: c - half, t1: c + half, y0, y1, exterior: exterior ?? this.isExterior(room, side) };
    room.openings.push(o);
    return o;
  }
  connect(a: Room, b: Room, width = 0.86, prefer?: number): boolean {
    const A = a.rect, B = b.rect, gap = INT + 0.05;
    let sa: Side, sb: Side, lo: number, hi: number;
    if (Math.abs(A.x1 - B.x0) < gap) { sa = 'e'; sb = 'w'; lo = Math.max(A.z0, B.z0); hi = Math.min(A.z1, B.z1); }
    else if (Math.abs(B.x1 - A.x0) < gap) { sa = 'w'; sb = 'e'; lo = Math.max(A.z0, B.z0); hi = Math.min(A.z1, B.z1); }
    else if (Math.abs(A.z1 - B.z0) < gap) { sa = 's'; sb = 'n'; lo = Math.max(A.x0, B.x0); hi = Math.min(A.x1, B.x1); }
    else if (Math.abs(B.z1 - A.z0) < gap) { sa = 'n'; sb = 's'; lo = Math.max(A.x0, B.x0); hi = Math.min(A.x1, B.x1); }
    else return false;
    if (hi - lo < width + 0.12) {
      if (hi - lo >= 0.72) width = hi - lo - 0.12; else return false;
    }
    const c = prefer === undefined ? (lo + hi) / 2 : Math.min(Math.max(prefer, lo + width / 2 + 0.06), hi - width / 2 - 0.06);
    const mk = (side: Side, to: string): Opening => ({ kind: 'door', side, t0: c - width / 2, t1: c + width / 2, y0: 0, y1: 2.05, exterior: false, to });
    a.openings.push(mk(sa, b.id)); b.openings.push(mk(sb, a.id));
    return true;
  }
  windows(room: Room, side: Side, width: number, sill: number, head: number, kind: Opening['kind'] = 'window'): void {
    if (!this.isExterior(room, side)) return;
    const [lo, hi] = side === 'n' || side === 's' ? [room.rect.x0, room.rect.x1] : [room.rect.z0, room.rect.z1];
    const len = hi - lo;
    if (len < width + 0.4) return;
    const n = Math.max(1, Math.min(4, Math.floor(len / 2.8)));
    for (let i = 0; i < n; i++) {
      const c = lo + (len * (i + 0.5)) / n;
      room.openings.push({ kind, side, t0: c - width / 2, t1: c + width / 2, y0: sill, y1: head, exterior: true });
    }
  }
}

// ---------------------------------------------------------------- entry point
export function planBuilding(b: CityBuilding, ctx: PlanContext, opts: { furnish?: boolean } = {}): BuildingPlan {
  const r = rngFor('plan', b.id);
  const obb = minAreaOBB(b.poly);
  const local = b.poly.map(([x, z]) => toLocal(obb, x, z));
  const isHouse = b.kind === 'house';
  const minSide = b.kind === 'block' ? 6 : isHouse ? 3 : 4;
  let wings: Wing[] = rectCover(local, isHouse ? 0.5 : 1.0, minSide).map((w) => ({ x0: rnd1(w.x0), z0: rnd1(w.z0), x1: rnd1(w.x1), z1: rnd1(w.z1) }));
  wings.sort((a, b2) => (b2.x1 - b2.x0) * (b2.z1 - b2.z0) - (a.x1 - a.x0) * (a.z1 - a.z0));
  const biggest = (wings[0].x1 - wings[0].x0) * (wings[0].z1 - wings[0].z0);
  wings = wings.filter((w, i) => i === 0 || (w.x1 - w.x0) * (w.z1 - w.z0) > biggest * 0.08).slice(0, 4);

  const road = ctx.roadNear(obb.cx, obb.cz);
  const levels = Math.max(1, b.levels);
  const shops = b.kind === 'block' && levels >= 9 && !!road && (road.kind === 'primary' || road.kind === 'secondary') && road.dist < 34;
  const floorY: number[] = [];
  let y = b.kind === 'block' ? (shops ? 0.15 : 0.75) : isHouse ? 0.45 : 0.3;
  for (let f = 0; f < levels; f++) {
    floorY.push(+y.toFixed(3));
    y += b.kind === 'block' ? (f === 0 && shops ? 3.2 : SH) : isHouse ? 2.85 : 3.5;
  }
  const height = +(y - 0.0).toFixed(3);
  const label = b.name && /bl/i.test(b.name) ? b.name.replace(/^bloc(ul)?\s*/i, 'Bl. ') : b.kind === 'block' ? `Bl. ${1 + (rngFor('bl', b.id)() * 98) | 0}` : (b.street ? `${b.street} ${b.number}`.trim() : '');
  const plan: BuildingPlan = {
    id: b.id, kind: b.kind, label,
    frame: { cx: +obb.cx.toFixed(3), cz: +obb.cz.toFixed(3), angle: +obb.angle.toFixed(5) },
    wings, levels, floorY, height,
    style: {
      panel: pick(r, PANEL), accent: pick(r, ACCENT), frame: pick(r, FRAMES),
      roof: isHouse ? (chance(r, 0.6) ? 'tile' : 'tin') : 'flat', parapet: chance(r, 0.45) ? 'mosaic' : 'panel',
      wall: b.kind === 'block' ? 'panel' : isHouse || b.kind === 'church' ? 'plaster' : b.kind === 'industrial' || b.kind === 'garage' ? 'brick' : 'panel',
    },
    rooms: [], units: [], stairs: [], balconies: [], entrances: [], landings: [] as Landing[],
  };
  const L = new Layout(plan, r);
  // which side of the main wing faces the road
  let roadSide: 'n' | 's' = 'n';
  if (road) {
    const c = Math.cos(obb.angle), s = Math.sin(obb.angle);
    const lz = road.dx * s + road.dz * c;
    roadSide = lz < 0 ? 'n' : 's';
  }
  const entrancesLocal = b.entrances.map((e) => ({ p: toLocal(obb, e.p[0], e.p[1]), name: e.name }));

  if (b.kind === 'block' || (levels >= 2 && !isHouse)) {
    const c = Math.cos(obb.angle), sn = Math.sin(obb.angle);
    wings.forEach((w, wi) => {
      const [wx, wz] = toWorld(obb, (w.x0 + w.x1) / 2, (w.z0 + w.z1) / 2);
      const h = ctx.roadNear(wx, wz);
      const wr = h ? { lx: h.dx * c - h.dz * sn, lz: h.dx * sn + h.dz * c, kind: h.kind } : null;
      sectionWing(L, w, wi, b, entrancesLocal, wr, shops);
    });
  } else if (isHouse) {
    houseLayout(L, b, roadSide);
  } else {
    singleStorey(L, b, roadSide);
  }
  plan.rooms = L.rooms;
  plan.units = L.units;
  if (opts.furnish !== false) {
    furnishPlan(plan);
    populatePlan(plan);
  }
  return plan;
}
const rnd1 = (v: number) => Math.round(v * 10) / 10;

// ---------------------------------------------------------------- prefab blocks (and multi-storey public buildings)
/** Canonical (u, v) → building-local point. */
function toLoc(u: number, v: number, T: Frame): { x: number; z: number } {
  const vv = T.flip ? -v : v;
  return T.swap ? { x: vv, z: u } : { x: u, z: vv };
}
interface WingRoad { lx: number; lz: number; kind: RoadKind }
function sectionWing(L: Layout, w: Wing, wi: number, b: CityBuilding, ents: { p: [number, number]; name: string }[], road: WingRoad | null, shops: boolean) {
  const p = L.plan;
  const r = L.r;
  // canonical frame: u along the wing's long side, v across it with the entrance side at low v
  const swap = w.z1 - w.z0 > w.x1 - w.x0 + 0.01;
  const U0 = swap ? w.z0 : w.x0, U1 = swap ? w.z1 : w.x1;
  const v0 = swap ? w.x0 : w.z0, v1 = swap ? w.x1 : w.z1;
  const W = U1 - U0, D = v1 - v0;
  const residential = b.kind === 'block';
  const eu = (e: { p: [number, number] }) => (swap ? e.p[1] : e.p[0]), ev = (e: { p: [number, number] }) => (swap ? e.p[0] : e.p[1]);
  const near = (side: 'n' | 's') => ents.filter((e) => eu(e) > U0 - 0.5 && eu(e) < U1 + 0.5 && Math.abs(ev(e) - (side === 'n' ? v0 : v1)) < 2.5);
  // the road side, in the wing's unflipped canonical terms
  const roadSide: 'n' | 's' = road ? ((swap ? road.lx : road.lz) < 0 ? 'n' : 's') : 'n';
  // entrance side: where the real entrances are, else away from the boulevard for tall blocks with shops
  let front: 'n' | 's' = shops ? (roadSide === 'n' ? 's' : 'n') : roadSide;
  const nN = near('n').length, nS = near('s').length;
  if (nN + nS > 0) front = nN >= nS ? 'n' : 's';
  const T: Frame = { swap, flip: front === 's' };
  const Z0 = T.flip ? -v1 : v0, Z1 = T.flip ? -v0 : v1;
  // stair cores: at the real entrances, else every ~17 m
  let cores = near(front).map(eu).sort((a, b2) => a - b2);
  const minSec = residential ? 9.8 : 9;
  cores = cores.filter((c, i) => i === 0 || c - cores[i - 1] > minSec);
  if (!cores.length || W < minSec) {
    const n = Math.max(1, Math.round(W / 17.5));
    cores = Array.from({ length: n }, (_, i) => U0 + (W * (i + 0.5)) / n);
  }
  cores = cores.map((c) => Math.min(Math.max(c, U0 + 4.4), U1 - 4.4));
  // a short wing has one flat per floor with the stairs at the end, not two slivers
  if (W < 11.5) cores = [U0 + 1.4];
  const bounds = [U0, ...cores.slice(1).map((c, i) => (cores[i] + c) / 2), U1];
  // depth bands: front rooms, the flat's hall (deep enough for a door off it), back rooms
  const Df = Math.min(4.6, Math.max(3.2, D * 0.38));
  const Dm = D < 8.4 ? 1.36 : 1.45;
  const zF1 = Z0 + Df, zM1 = zF1 + Dm;
  const back = Z1 - zM1 > 2.6;
  const CH = 1.4;
  let apt = 0;
  const scLetters = 'ABCDEFGH';
  cores.forEach((c, si) => {
    const s0 = bounds[si], s1 = bounds[si + 1];
    const sc = `Sc. ${scLetters[(wi * 3 + si) % scLetters.length]}`;
    const coreCell: Rect = { x0: c - CH, x1: c + CH, z0: Z0, z1: back ? zM1 : Z1 };
    const leftW = c - CH - s0, rightW = s1 - (c + CH);
    const behindToRight = leftW < 2.4 || rightW <= leftW;
    const ent = toLoc(c, Z0, T);
    p.entrances.push({ x: ent.x, z: ent.z, side: L.side('n', T), label: `${p.label}, ${sc}` });
    for (let f = 0; f < p.levels; f++) {
      const stair = L.room(f === 0 ? 'lobby' : 'stair', f, coreCell, T);
      const rise = (f + 1 < p.levels ? p.floorY[f + 1] : p.height) - p.floorY[f];
      if (f === 0) L.open(stair, 'n', c, 1.4, 0, 2.25, 'entrance', T, true);
      else if (f + 1 < p.levels) L.open(stair, 'n', c, 1.1, rise / 2 + 0.6, rise / 2 + 1.7, 'stairwindow', T, true);
      stairsFor(p, c, Z0, coreCell.z1, f, T);
      const floorLabel = f === 0 ? 'Parter' : `Et. ${f}`;
      const shopFloor = shops && f === 0;
      for (const sideLR of ['L', 'R'] as const) {
        const ax0 = sideLR === 'L' ? s0 : c + CH, ax1 = sideLR === 'L' ? c - CH : s1;
        const takesBehind = back && ((sideLR === 'R') === behindToRight);
        const bx0 = takesBehind && sideLR === 'R' ? c - CH : ax0, bx1 = takesBehind && sideLR === 'L' ? c + CH : ax1;
        const width = ax1 - ax0;
        if (width < 2.4) continue;
        if (shopFloor) {
          // a shop through the full depth, its window on the boulevard (or whichever long side is open)
          const shop = L.room('shop', f, { x0: ax0, x1: ax1, z0: Z0, z1: Z1 }, T);
          const roadCanon: Side = roadSide === front ? 'n' : 's';
          const shopSide = [L.side(roadCanon, T), L.side(roadCanon === 'n' ? 's' : 'n', T)].find((sd) => L.isExterior(shop, sd));
          if (shopSide) {
            const [lo, hi] = shopSide === 'n' || shopSide === 's' ? [shop.rect.x0, shop.rect.x1] : [shop.rect.z0, shop.rect.z1];
            shop.openings.push({ kind: 'shopfront', side: shopSide, t0: lo + 0.35, t1: hi - 1.55, y0: 0.45, y1: 2.95, exterior: true });
            shop.openings.push({ kind: 'entrance', side: shopSide, t0: hi - 1.35, t1: hi - 0.35, y0: 0, y1: 2.5, exterior: true });
          } else L.connect(shop, stair, 0.9);
          if (takesBehind) {
            const store = L.room('storage', f, { x0: c - CH, x1: c + CH, z0: zM1, z1: Z1 }, T);
            L.connect(shop, store);
          }
          L.units.push({ id: shop.id + '/u', kind: 'shop', label: `${p.label}, magazin`, floor: f, rooms: [shop.id], household: [], family: '' });
          continue;
        }
        if (!residential) {
          // classrooms, offices, workshops: one room per half, entered from the landing
          const type: RoomType = b.kind === 'school' ? 'classroom' : b.kind === 'industrial' ? 'workshop' : 'office';
          const rm = L.room(type, f, { x0: ax0, x1: ax1, z0: Z0, z1: Z1 }, T);
          L.connect(rm, stair, 1.0);
          L.windows(rm, L.side('n', T), 1.6, 0.9, 2.5); L.windows(rm, L.side('s', T), 1.6, 0.9, 2.5);
          if (takesBehind) { const st = L.room('storage', f, { x0: c - CH, x1: c + CH, z0: zM1, z1: Z1 }, T); L.connect(rm, st); }
          L.units.push({ id: rm.id + '/u', kind: 'public', label: `${p.label} ${floorLabel}`, floor: f, rooms: [rm.id], household: [], family: '' });
          continue;
        }
        apt++;
        const unitRooms: Room[] = [];
        // front band (entrance side): bath next to the core, kitchen, maybe a small bedroom.
        // A narrow flat keeps only the kitchen in front and moves the bath to the back.
        const frontCells: [RoomType, number][] = [];
        const bathW = width > 5.4 ? 2.0 : 1.6;
        const bathBack = back && width - bathW < 2.3 && bx1 - bx0 >= 1.7 + 2.4;
        let rem = width;
        if (!bathBack) { frontCells.push(['bath', bathW]); rem -= bathW; }
        if (rem > 6.0) { frontCells.push(['kitchen', 3.2]); rem -= 3.2; frontCells.push(['kids', rem]); }
        else frontCells.push(['kitchen', rem]);
        if (sideLR === 'L') frontCells.reverse();
        let x = ax0;
        for (const [type, cw] of frontCells) { const rm = L.room(type, f, { x0: x, x1: x + cw, z0: Z0, z1: zF1 }, T); unitRooms.push(rm); x += cw; }
        const hall = L.room('hall', f, { x0: ax0, x1: ax1, z0: zF1, z1: zM1 }, T);
        unitRooms.push(hall);
        if (back) {
          // back band: living room (taking the space behind the stairs), bedrooms
          let bw = bx1 - bx0;
          const cells: [RoomType, number][] = [];
          if (bathBack) { cells.push(['bath', 1.7]); bw -= 1.7; }
          let livW = Math.min(Math.max(bw * 0.55, takesBehind ? CH * 2 + 1.4 : 3.6), 6.2);
          let rest = bw - livW;
          if (rest < 2.6) { livW = bw; rest = 0; }
          cells.push(['living', livW]);
          if (rest > 6.4) { cells.push(['bedroom', rest / 2], ['kids', rest / 2]); } else if (rest > 0) cells.push(['bedroom', rest]);
          if (sideLR === 'L') cells.reverse();
          let bx = bx0;
          for (const [type, cw] of cells) { const rm = L.room(type, f, { x0: bx, x1: bx + cw, z0: zM1, z1: Z1 }, T); unitRooms.push(rm); bx += cw; }
        }
        // doors: every room opens onto the hall, the hall onto the landing; a room the hall
        // does not reach (it sits behind the stair core) opens into its neighbour instead
        for (const rm of unitRooms) {
          if (rm === hall) continue;
          if (!L.connect(rm, hall, rm.type === 'bath' ? 0.7 : 0.82)) {
            const nb = unitRooms.find((o) => o !== rm && o !== hall && o.type !== 'bath' && L.connect(rm, o, 0.82));
            void nb;
          }
        }
        L.connect(hall, stair, 0.92);
        // windows
        for (const rm of unitRooms) {
          for (const sd of ['n', 's', 'e', 'w'] as Side[]) {
            if (!L.isExterior(rm, sd)) continue;
            const gable = sd !== L.side('n', T) && sd !== L.side('s', T);
            if (gable && !(rm.type === 'bedroom' || rm.type === 'kids' || rm.type === 'kitchen')) continue;
            if (gable && !chance(r, 0.6)) continue;
            if (rm.type === 'bath') { if (!gable) L.windows(rm, sd, 0.6, 1.5, 2.1); continue; }
            if (rm.type === 'hall') continue;
            if (rm.type === 'kitchen') { L.windows(rm, sd, 1.2, 1.0, 2.2); continue; }
            if (rm.type === 'living' && !gable && f > 0) {
              // balcony door and window
              const [lo, hi] = sd === 'n' || sd === 's' ? [rm.rect.x0, rm.rect.x1] : [rm.rect.z0, rm.rect.z1];
              const mid = (lo + hi) / 2;
              if (hi - lo < 2.8) { L.windows(rm, sd, 1.4, 0.85, 2.25); continue; }
              rm.openings.push({ kind: 'balcony', side: sd, t0: mid - 1.25, t1: mid - 0.45, y0: 0, y1: 2.15, exterior: true });
              rm.openings.push({ kind: 'window', side: sd, t0: mid - 0.35, t1: mid + 1.0, y0: 0.9, y1: 2.15, exterior: true });
              p.balconies.push({ side: sd, t0: mid - 1.55, t1: mid + 1.3, floor: f, y: p.floorY[f], depth: 1.1, enclosed: chance(r, 0.35), laundry: chance(r, 0.3), flag: chance(r, 0.06) });
              continue;
            }
            L.windows(rm, sd, rm.type === 'living' ? 1.7 : 1.4, 0.85, 2.25);
          }
        }
        const label = `${p.label}, ${sc}, ${floorLabel}, Ap. ${apt}`;
        L.units.push({ id: hall.id + '/u', kind: 'flat', label, floor: f, rooms: unitRooms.map((u) => u.id), household: [], family: '' });
      }
    }
  });
}

/** Stair flights and landings inside one core for one storey (canonical frame in, local out). */
function stairsFor(p: BuildingPlan, c: number, Z0: number, coreZ1: number, f: number, T: Frame) {
  const yF = p.floorY[f];
  const top = f + 1 < p.levels ? p.floorY[f + 1] : null;
  const zIn0 = Z0 + EXT, zIn1 = coreZ1 - INT / 2;
  const zL0 = zIn1 - 1.26;     // back landing (apartment doors)
  const zH1 = zIn0 + 1.25;     // front half-landing
  const laneA = [c - 1.28, c - 0.06], laneB = [c + 0.06, c + 1.28];
  const rect = (x0: number, z0: number, x1: number, z1: number) => mapRect({ x0, z0, x1, z1 }, T);
  const axis = T.swap ? 'x' : 'z';
  // a flight climbing toward +v canonically climbs toward -v when flipped
  const dir = (d: 1 | -1): 1 | -1 => (T.flip ? (-d as 1 | -1) : d);
  if (f === 0) {
    p.landings.push({ ...rect(c - CHW, zIn0, c + CHW, zIn1), y: yF });
    if (top !== null) p.stairs.push({ ...rect(laneB[0], zIn0 + 1.2, laneB[1], zL0), yA: yF, yB: top, axis, dir: dir(1) });
    return;
  }
  p.landings.push({ ...rect(c - CHW, zL0, c + CHW, zIn1), y: yF });
  if (top === null) return;
  const mid = (yF + top) / 2;
  p.landings.push({ ...rect(c - CHW, zIn0, c + CHW, zH1), y: mid });
  // flight A runs from the back landing toward the front, flight B back again
  p.stairs.push({ ...rect(laneA[0], zH1, laneA[1], zL0), yA: yF, yB: mid, axis, dir: dir(-1) });
  p.stairs.push({ ...rect(laneB[0], zH1, laneB[1], zL0), yA: mid, yB: top, axis, dir: dir(1) });
}
const CHW = 1.34;

// ---------------------------------------------------------------- old single- and two-storey houses
function houseLayout(L: Layout, _b: CityBuilding, roadSide: 'n' | 's') {
  const p = L.plan;
  const r = L.r;
  const w = p.wings[0];
  const flip = roadSide === 's';
  const T: Frame = { swap: false, flip };
  const Z0 = flip ? -w.z1 : w.z0, Z1 = flip ? -w.z0 : w.z1;
  const W = w.x1 - w.x0, D = Z1 - Z0;
  if (W < 4.6 || D < 3.4) {
    // a one-room cottage or summer house: the door opens straight into it
    const all: Room[] = [];
    for (let f = 0; f < p.levels; f++) {
      const rm = L.room(f === 0 ? 'living' : 'storage', f, { x0: w.x0, x1: w.x1, z0: Z0, z1: Z1 }, T);
      all.push(rm);
      if (f === 0) {
        L.open(rm, 'n', (w.x0 + w.x1) / 2 - 0.4, 0.9, 0, 2.05, 'entrance', T, true);
        p.entrances.push({ x: (w.x0 + w.x1) / 2 - 0.4, z: flip ? -Z0 : Z0, side: flip ? 's' : 'n', label: p.label || 'casă' });
      } else {
        // a ladder up to the loft
        const lad = mapRect({ x0: w.x0 + 0.2, x1: w.x0 + 0.9, z0: Z1 - 1.6, z1: Z1 - 0.3 }, T);
        p.stairs.push({ ...lad, yA: p.floorY[f - 1], yB: p.floorY[f], axis: 'z', dir: flip ? 1 : -1 });
        rm.voidFloor = lad; all[f - 1].voidCeil = lad;
      }
      for (const sd of ['n', 's', 'e', 'w'] as Side[]) if (L.isExterior(rm, sd)) L.windows(rm, sd, 0.9, 0.9, 2.0);
    }
    L.units.push({ id: p.id + '/house', kind: 'house', label: p.label || 'casă', floor: 0, rooms: all.map((a) => a.id), household: [], family: '' });
    return;
  }
  const twoBand = D >= 7.2;
  const zB = Z0 + (twoBand ? D * 0.58 : D);
  const hallW = Math.max(1.55, Math.min(2.4, W * 0.3));
  const hallLeft = chance(r, 0.5);
  const hx0 = hallLeft ? w.x0 : w.x1 - hallW, hx1 = hx0 + hallW;
  const rx0 = hallLeft ? hx1 : w.x0, rx1 = hallLeft ? w.x1 : hx0;
  const all: Room[] = [];
  let upperVoid: { x0: number; z0: number; x1: number; z1: number } | null = null;
  for (let f = 0; f < p.levels; f++) {
    const hall = L.room('hall', f, { x0: hx0, x1: hx1, z0: Z0, z1: Z1 }, T);
    all.push(hall);
    if (upperVoid) { hall.voidFloor = upperVoid; upperVoid = null; }
    if (f === 0) {
      L.open(hall, 'n', (hx0 + hx1) / 2, 0.95, 0, 2.1, 'entrance', T, true);
      p.entrances.push({ x: (hx0 + hx1) / 2, z: flip ? -Z0 : Z0, side: flip ? 's' : 'n', label: p.label || 'casă' });
    }
    if (f + 1 < p.levels) {
      const zz0 = Z0 + 0.6, zz1 = Math.min(Z1 - 0.5, zz0 + 3.6);
      const lane = [hx0 + 0.15, hx0 + Math.min(1.0, hallW - 0.2)];
      const rect = flip ? { x0: lane[0], x1: lane[1], z0: -zz1, z1: -zz0 } : { x0: lane[0], x1: lane[1], z0: zz0, z1: zz1 };
      p.stairs.push({ ...rect, yA: p.floorY[f], yB: p.floorY[f + 1], axis: 'z', dir: flip ? -1 : 1 });
      hall.voidCeil = { ...rect };
      upperVoid = { ...rect };
      p.landings.push({ ...(flip ? { x0: hx0, x1: hx1, z0: -Z1, z1: -zz1 } : { x0: hx0, x1: hx1, z0: zz1, z1: Z1 }), y: p.floorY[f + 1] });
    }
    const RW = rx1 - rx0;
    const front: [RoomType, number][] = f === 0 ? (RW > 7 ? [['living', RW * 0.56], ['bedroom', RW * 0.44]] : [['living', RW]]) : (RW > 6 ? [['bedroom', RW / 2], ['kids', RW / 2]] : [['bedroom', RW]]);
    const backs: [RoomType, number][] = twoBand ? (f === 0 ? (RW > 5.5 ? [['kitchen', RW * 0.6], ['bath', RW * 0.4]] : [['kitchen', RW]]) : [['storage', RW]]) : [];
    if (!hallLeft) { front.reverse(); backs.reverse(); }
    const fr: Room[] = [], bk: Room[] = [];
    let x = rx0;
    for (const [t, cw] of front) { fr.push(L.room(t, f, { x0: x, x1: x + cw, z0: Z0, z1: zB }, T)); x += cw; }
    x = rx0;
    for (const [t, cw] of backs) { bk.push(L.room(t, f, { x0: x, x1: x + cw, z0: zB, z1: Z1 }, T)); x += cw; }
    for (const rm of [...fr, ...bk]) {
      all.push(rm);
      if (!L.connect(rm, hall)) {
        const nb = [...fr, ...bk].find((o) => o !== rm && L.connect(rm, o));
        void nb;
      }
      for (const sd of ['n', 's', 'e', 'w'] as Side[]) {
        if (!L.isExterior(rm, sd)) continue;
        if (rm.type === 'bath') { L.windows(rm, sd, 0.55, 1.45, 2.0); continue; }
        if (rm.type === 'storage' && chance(r, 0.6)) continue;
        L.windows(rm, sd, 1.1, 0.9, 2.2);
      }
    }
    if (fr.length > 1) L.connect(fr[0], fr[1]);
    if (fr[0] && bk[0]) L.connect(fr[0], bk[0]);
  }
  // extra wings: a summer kitchen, a storeroom or the glazed porch
  p.wings.slice(1).forEach((wg) => {
    const narrow = Math.min(wg.x1 - wg.x0, wg.z1 - wg.z0) < 3.2;
    const rm = L.room(narrow ? 'porch' : chance(r, 0.5) ? 'storage' : 'kitchen', 0, { x0: wg.x0, x1: wg.x1, z0: wg.z0, z1: wg.z1 }, F0);
    all.push(rm);
    const target = all.find((o) => o !== rm && o.floor === 0 && L.connect(rm, o));
    if (!target) L.open(rm, 'n', (rm.rect.x0 + rm.rect.x1) / 2, 0.9, 0, 2.05, 'entrance', F0, true);
    for (const sd of ['n', 's', 'e', 'w'] as Side[]) if (L.isExterior(rm, sd)) L.windows(rm, sd, narrow ? 0.9 : 1.0, 0.9, 2.1);
  });
  L.units.push({ id: p.id + '/house', kind: 'house', label: p.label || 'casă', floor: 0, rooms: all.map((a) => a.id), household: [], family: '' });
}

// ---------------------------------------------------------------- one-storey public buildings: shops, garages, halls, workshops, churches
function singleStorey(L: Layout, b: CityBuilding, roadSide: 'n' | 's') {
  const p = L.plan;
  const kind = b.kind;
  const type: RoomType = kind === 'shop' ? 'shop' : kind === 'church' ? 'nave' : kind === 'garage' ? 'garage' : kind === 'industrial' ? 'workshop' : kind === 'school' ? 'classroom' : 'office';
  p.wings.forEach((w, wi) => {
    const flip = roadSide === 's';
    const T: Frame = { swap: false, flip };
    const Z0 = flip ? -w.z1 : w.z0, Z1 = flip ? -w.z0 : w.z1;
    const W = w.x1 - w.x0;
    const rooms: Room[] = [];
    if (kind === 'garage') {
      const n = Math.max(1, Math.round(W / 3.2));
      for (let i = 0; i < n; i++) {
        const g = L.room('garage', 0, { x0: w.x0 + (W * i) / n, x1: w.x0 + (W * (i + 1)) / n, z0: Z0, z1: Z1 }, T);
        L.open(g, 'n', (g.rect.x0 + g.rect.x1) / 2, Math.min(2.4, g.rect.x1 - g.rect.x0 - 0.3), 0, 2.1, 'entrance', T, true);
        rooms.push(g);
      }
    } else {
      const splitAt = type === 'workshop' || type === 'nave' ? 1e9 : 14;
      const n = Math.max(1, Math.round(W / splitAt));
      for (let i = 0; i < n; i++) rooms.push(L.room(type, 0, { x0: w.x0 + (W * i) / n, x1: w.x0 + (W * (i + 1)) / n, z0: Z0, z1: Z1 }, T));
      for (let i = 1; i < rooms.length; i++) L.connect(rooms[i - 1], rooms[i], 1.0);
      const main = rooms[Math.floor(rooms.length / 2)];
      if (wi === 0) {
        L.open(main, 'n', (main.rect.x0 + main.rect.x1) / 2, type === 'workshop' ? 3.0 : 1.4, 0, type === 'workshop' ? 3.2 : 2.4, 'entrance', T, true);
        p.entrances.push({ x: (main.rect.x0 + main.rect.x1) / 2, z: flip ? -Z0 : Z0, side: flip ? 's' : 'n', label: p.label });
      } else {
        const prev = L.rooms.find((o) => o.floor === 0 && !rooms.includes(o) && L.connect(main, o));
        if (!prev) L.open(main, 'n', (main.rect.x0 + main.rect.x1) / 2, 1.2, 0, 2.3, 'entrance', T, true);
      }
      for (const rm of rooms) for (const sd of ['n', 's', 'e', 'w'] as Side[]) {
        if (!L.isExterior(rm, sd)) continue;
        if (rm.type === 'shop' && sd === L.side('n', T)) { rm.openings.push({ kind: 'shopfront', side: sd, t0: rm.rect.x0 + 0.4, t1: Math.max(rm.rect.x0 + 1, (rm.rect.x0 + rm.rect.x1) / 2 - 1.0), y0: 0.45, y1: 2.6, exterior: true }); continue; }
        L.windows(rm, sd, rm.type === 'workshop' ? 2.4 : rm.type === 'nave' ? 0.9 : 1.5, rm.type === 'nave' ? 1.6 : 1.0, rm.type === 'workshop' ? 3.0 : 2.4);
      }
    }
    for (const rm of rooms) L.units.push({ id: rm.id + '/u', kind: kind === 'garage' ? 'public' : kind === 'shop' ? 'shop' : 'public', label: p.label || kindLabel(kind), floor: 0, rooms: [rm.id], household: [], family: '' });
  });
}
function kindLabel(k: string): string {
  return ({ shop: 'magazin', church: 'biserică', garage: 'garaj', industrial: 'atelier', school: 'şcoală', service: 'clădire tehnică', hall: 'sală' } as Record<string, string>)[k] || 'clădire';
}
