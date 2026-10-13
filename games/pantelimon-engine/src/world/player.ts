// First-person body: walking, running, gravity, stepping up stairs and kerbs.
import type { Collider } from './collide';

export interface Input { fwd: number; right: number; run: boolean; jump: boolean }
export class Player {
  x = 0; y = 0; z = 0; vy = 0; yaw = 0; pitch = 0; onGround = true;
  speed = 0; bob = 0;
  readonly eye = 1.62;
  step(inp: Input, dt: number, col: Collider) {
    const sp = (inp.run ? 4.2 : 1.6);
    const l = Math.hypot(inp.fwd, inp.right) || 1;
    const fx = -Math.sin(this.yaw), fz = -Math.cos(this.yaw);
    const rx = Math.cos(this.yaw), rz = -Math.sin(this.yaw);
    const mx = ((fx * inp.fwd + rx * inp.right) / l) * sp, mz = ((fz * inp.fwd + rz * inp.right) / l) * sp;
    // substeps keep fast movement from tunnelling through thin walls
    const n = Math.max(1, Math.ceil((Math.hypot(mx, mz) * dt) / 0.1));
    for (let i = 0; i < n; i++) {
      const p = { x: this.x + (mx * dt) / n, z: this.z + (mz * dt) / n };
      col.resolve(p, this.y);
      const g = col.groundAt(p.x, p.z, this.y);
      this.x = p.x; this.z = p.z;
      if (this.onGround && g < this.y && this.y - g < 0.45) this.y = g; // walk down steps
      else if (g > this.y) { this.y = g; this.vy = Math.max(this.vy, 0); }
    }
    const g = col.groundAt(this.x, this.z, this.y);
    if (inp.jump && this.onGround) { this.vy = 3.6; this.onGround = false; }
    this.vy -= 9.81 * dt;
    this.y += this.vy * dt;
    if (this.y <= g) { this.y = g; this.vy = 0; this.onGround = true; } else this.onGround = this.y - g < 0.02;
    const moving = Math.hypot(mx, mz);
    this.speed = moving;
    if (this.onGround) this.bob += dt * moving * 2.2;
  }
}
