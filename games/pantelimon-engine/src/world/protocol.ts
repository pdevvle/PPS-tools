// Messages between the main thread and the mesh worker. Everything is
// plain data plus typed arrays, so it moves across with zero copies.
import type { BuildingPlan, CityData } from '../data/schema';
import type { MeshData } from '../mesh/builder';
import type { FurnInstance } from '../mesh/building';

export interface PropInstance { key: string; m: number[]; type: string; x: number; z: number; rot: number }
export type ToWorker =
  | { t: 'init'; data: CityData }
  | { t: 'tile'; key: string }
  | { t: 'near'; bi: number }
  | { t: 'floor'; bi: number; f: number };
export type FromWorker =
  | { t: 'ready' }
  | { t: 'tile'; key: string; ground: MeshData; shells: MeshData; heights: Float32Array; n: number; x0: number; z0: number; props: PropInstance[]; buildings: number[]; ms: number }
  | { t: 'near'; bi: number; plan: BuildingPlan; exterior: MeshData; glass: MeshData; plugs: MeshData[]; ms: number }
  | { t: 'floor'; bi: number; f: number; shell: MeshData; inst: FurnInstance[]; ms: number };
