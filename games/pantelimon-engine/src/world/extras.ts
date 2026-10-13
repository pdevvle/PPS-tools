// ===================================================================
// Derived pieces of a building plan that the mesher and the collision
// both need: the steps up to each entrance.
// ===================================================================
import type { BuildingPlan } from '../data/schema';
export { EXT, INT } from '../gen/plan';

export interface ExtSteps { side: 'n' | 's' | 'e' | 'w'; c: number; t0: number; t1: number; rise: number; depth: number; steps: number; canopy: boolean }

export function exteriorSteps(plan: BuildingPlan): ExtSteps[] {
  const rise = plan.floorY[0];
  if (rise < 0.2) return [];
  const steps = Math.max(1, Math.round(rise / 0.15));
  const width = plan.kind === 'block' ? 1.9 : plan.kind === 'house' ? 1.2 : 1.7;
  return plan.entrances.map((e) => {
    const ns = e.side === 'n' || e.side === 's';
    const t = ns ? e.x : e.z;
    return { side: e.side, c: ns ? e.z : e.x, t0: t - width / 2, t1: t + width / 2, rise, depth: steps * 0.3, steps, canopy: plan.kind === 'block' };
  });
}
