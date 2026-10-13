// ===================================================================
// The port format. Everything the generators produce is plain JSON in
// these shapes, with no references to three.js, the DOM or this engine,
// so another engine (Unity, Godot, Unreal) can read the same data.
//
// Conventions
// - Units are metres. World axes: x east, z south, y up.
// - Angles are radians about +y, using the rotateY convention:
//     world.x = cx + lx·cos(a) + lz·sin(a)
//     world.z = cz − lx·sin(a) + lz·cos(a)
// - Building-local frame: origin at the footprint's oriented bounding-box
//   centre, local x along the long side, ground level y = 0.
// ===================================================================

export type V2 = [number, number];

// ---------------------------------------------------------------- input: the city (from tools/osm-1989.mjs)
export type RoadKind = 'primary' | 'secondary' | 'tertiary' | 'residential' | 'living_street' | 'unclassified' | 'service' | 'path';
export interface CityRoad { id: string; kind: RoadKind; name: string; width: number; oneway: boolean; surface: 'asphalt' | 'cobble' | 'dirt'; layer: number; bridge: boolean; pts: V2[] }
export type BuildingKind = 'block' | 'house' | 'school' | 'industrial' | 'church' | 'garage' | 'shop' | 'service' | 'hall';
export interface CityBuilding {
  id: string; osm: string; kind: BuildingKind; levels: number;
  name: string; street: string; number: string;
  poly: V2[];
  entrances: { p: V2; name: string; kind: string }[];
}
export interface CityArea { id: string; kind: 'grass' | 'playground' | 'pitch' | 'parking'; poly: V2[] }
export interface CityData {
  version: number; name: string; date: string; attribution: string;
  origin: { lat: number; lon: number };
  bounds: { x0: number; z0: number; x1: number; z1: number };
  roads: CityRoad[]; trams: { id: string; pts: V2[] }[]; buildings: CityBuilding[]; areas: CityArea[]; trees: V2[];
}

// ---------------------------------------------------------------- generated: a building and everything inside it
export type RoomType =
  | 'living' | 'bedroom' | 'kids' | 'kitchen' | 'bath' | 'hall' | 'storage'
  | 'stair' | 'lobby' | 'shop' | 'classroom' | 'corridor' | 'office' | 'workshop' | 'nave' | 'garage' | 'porch';

/** An opening in a wall. `side` is the room side it sits on; t0..t1 run along that side in local coordinates. */
export interface Opening {
  to?: string;         // for doors: the room on the other side
  kind: 'window' | 'door' | 'balcony' | 'shopfront' | 'entrance' | 'stairwindow';
  side: 'n' | 's' | 'e' | 'w';   // n = −z, s = +z, w = −x, e = +x (in building-local axes)
  t0: number; t1: number;        // span along the wall (local x for n/s, local z for e/w)
  y0: number; y1: number;        // sill and head heights above the floor
  exterior: boolean;
}

export interface FurnitureItem {
  type: string;        // see FURNITURE_TYPES in gen/furnish.ts
  x: number; y: number; z: number; // building-local position of the item's base centre
  rot: number;         // about y; 0 = front faces +z
  variant: number;     // 0..n, picks colour or model variation
  on?: boolean;        // TVs, radios and lamps that are switched on
  w?: number; h?: number; // size override (curtains)
}

export interface Room {
  id: string;
  type: RoomType;
  floor: number;
  rect: { x0: number; z0: number; x1: number; z1: number }; // building-local
  y: number;           // floor elevation
  h: number;           // clear height
  openings: Opening[];
  furniture: FurnitureItem[];
  wallpaper: number;   // palette index
  lit: boolean;        // the household turns the light on after dark
  voidFloor?: { x0: number; z0: number; x1: number; z1: number };  // stairwell cut out of the floor
  voidCeil?: { x0: number; z0: number; x1: number; z1: number };   // and out of the ceiling below it
}

export type Pose = 'stand' | 'walk' | 'sit' | 'lie' | 'window' | 'cook' | 'chant' | 'phone' | 'read';
export interface Outfit { top: string; bottom: string; skin: string; hair: string; hat: 'none' | 'cap' | 'fur' | 'scarf' | 'knit'; skirt: boolean }
export interface Resident {
  id: string;
  name: string;
  age: number;
  sex: 'f' | 'm';
  role: string;        // 'mother', 'grandfather', 'tenant'...
  occupation: string;
  outfit: Outfit;
  activity: { pose: Pose; what: string; x: number; y: number; z: number; rot: number };
}

export interface Unit {
  id: string;
  kind: 'flat' | 'house' | 'shop' | 'public';
  label: string;       // 'Bl. 12, Sc. A, Et. 2, Ap. 9'
  floor: number;
  rooms: string[];     // room ids
  household: Resident[];
  family: string;      // surname on the door
}

export interface Flight { x0: number; z0: number; x1: number; z1: number; yA: number; yB: number; axis: 'x' | 'z'; dir: 1 | -1 }

export interface Balcony { side: 'n' | 's' | 'e' | 'w'; t0: number; t1: number; floor: number; y: number; depth: number; enclosed: boolean; laundry: boolean; flag: boolean }

export interface Wing { x0: number; z0: number; x1: number; z1: number }

export interface Landing { x0: number; z0: number; x1: number; z1: number; y: number }

export interface BuildingPlan {
  id: string;
  kind: BuildingKind;
  label: string;           // 'Bl. 12' or a street address
  frame: { cx: number; cz: number; angle: number };
  wings: Wing[];
  levels: number;
  floorY: number[];        // floor elevation of each level
  height: number;          // to the roof slab
  style: { panel: string; accent: string; frame: string; roof: 'flat' | 'tile' | 'tin'; parapet: 'mosaic' | 'panel'; wall: 'panel' | 'plaster' | 'brick' };
  rooms: Room[];
  units: Unit[];
  stairs: Flight[];
  landings: Landing[];
  balconies: Balcony[];
  entrances: { x: number; z: number; side: 'n' | 's' | 'e' | 'w'; label: string }[];
}

// ---------------------------------------------------------------- generated: street furniture for a tile
export interface PropPlacement { type: string; x: number; z: number; y: number; rot: number; variant: number; scale?: number }
