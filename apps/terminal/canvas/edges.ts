// [M5-FLOW-02] SUPPLIES edges: geometry resolution, value->thickness, and a pooled
// directional particle system (supplier->customer flow). Pure math + typed-array
// pooling here (no three import) so it stays testable and allocation-free per frame;
// Edges.tsx turns this into instanced cylinders + a Points cloud.

import type { Vec3 } from "./layout";
import type { GraphEdge } from "./types";

export interface EdgeLine {
  supplier: string;
  customer: string;
  a: Vec3; // supplier position (flow origin)
  b: Vec3; // customer position (flow destination)
  value: number | null; // trade_value -> thickness
  confidence: string;
  freshness: string;
}

// Resolve each edge to endpoint positions; drop edges whose nodes aren't placed.
export function buildEdges(
  edges: GraphEdge[],
  positions: Map<string, Vec3>,
): EdgeLine[] {
  const lines: EdgeLine[] = [];
  for (const e of edges) {
    const a = positions.get(e.supplier);
    const b = positions.get(e.customer);
    if (!a || !b) continue;
    lines.push({
      supplier: e.supplier,
      customer: e.customer,
      a,
      b,
      value: e.trade_value ?? null,
      confidence: e.confidence,
      freshness: e.freshness,
    });
  }
  return lines;
}

export function maxTradeValue(lines: EdgeLine[]): number {
  let max = 0;
  for (const l of lines) if (l.value && l.value > max) max = l.value;
  return max;
}

const MIN_RADIUS = 0.03;
const MAX_RADIUS = 0.22;

// Thickness scales with trade value (sqrt -> cross-section ~ value); unknown values
// draw at the thin floor so a relationship is still visible.
export function valueToRadius(value: number | null, maxValue: number): number {
  if (!value || value <= 0 || maxValue <= 0) return MIN_RADIUS;
  const t = Math.sqrt(value / maxValue); // 0..1
  return MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS);
}

// Low-discrepancy [0,1) sequence — deterministic spread without Math.random.
function halton(i: number, base: number): number {
  let f = 1;
  let r = 0;
  let n = i + 1;
  while (n > 0) {
    f /= base;
    r += f * (n % base);
    n = Math.floor(n / base);
  }
  return r;
}

/**
 * A fixed pool of flow particles, reused every frame (no per-frame allocation).
 * Particles are spread round-robin across edges so every edge flows; each advances
 * supplier(a) -> customer(b) and wraps. If edges*perEdge exceeds `cap`, coverage is
 * clamped and reported via `coveredEdges` (no silent truncation).
 */
export class ParticlePool {
  readonly count: number;
  readonly positions: Float32Array;
  readonly coveredEdges: number;
  private readonly edgeOf: Int32Array;
  private readonly phase: Float32Array;
  private readonly speed: Float32Array;

  constructor(edgeCount: number, perEdge = 6, cap = 5000, speed = 0.25) {
    this.count = edgeCount <= 0 ? 0 : Math.min(cap, edgeCount * perEdge);
    this.positions = new Float32Array(this.count * 3);
    this.edgeOf = new Int32Array(this.count);
    this.phase = new Float32Array(this.count);
    this.speed = new Float32Array(this.count);
    const covered = new Set<number>();
    for (let p = 0; p < this.count; p++) {
      const edge = p % edgeCount; // round-robin -> fair coverage even when capped
      this.edgeOf[p] = edge;
      covered.add(edge);
      this.phase[p] = halton(p, 2); // spread along the edge
      this.speed[p] = speed * (0.7 + 0.6 * halton(p, 3)); // slight variation
    }
    this.coveredEdges = covered.size;
  }

  // Advance every particle along its edge and write world positions.
  // Hidden particles are parked far past the camera's far plane so they clip out —
  // depth toggling needs no re-mount and no per-frame allocation.
  update(lines: EdgeLine[], dt: number, visible?: boolean[]): void {
    for (let p = 0; p < this.count; p++) {
      let t = this.phase[p] + this.speed[p] * dt;
      if (t >= 1) t -= Math.floor(t);
      this.phase[p] = t;
      const edge = this.edgeOf[p];
      const line = lines[edge];
      const o = p * 3;
      if (!line || (visible && !visible[edge])) {
        this.positions[o] = this.positions[o + 1] = this.positions[o + 2] = FAR;
        continue;
      }
      const [ax, ay, az] = line.a;
      const [bx, by, bz] = line.b;
      this.positions[o] = ax + (bx - ax) * t;
      this.positions[o + 1] = ay + (by - ay) * t;
      this.positions[o + 2] = az + (bz - az) * t;
    }
  }
}

const FAR = 1e6;
