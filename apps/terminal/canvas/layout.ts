// [M5-CANVAS-01] Deterministic 3D node layout. A Fibonacci sphere spreads hundreds
// of nodes evenly with no force simulation, so positions are stable across renders
// (depth/edge layers in later tasks build on these). Force/cluster layouts can
// replace this behind the same {ticker -> position} contract.

export type Vec3 = [number, number, number];

export function fibonacciSphere(count: number, radius: number): Vec3[] {
  if (count <= 0) return [];
  if (count === 1) return [[0, 0, 0]];
  const points: Vec3[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5)); // golden angle
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2; // 1 .. -1
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    points.push([
      Math.cos(theta) * r * radius,
      y * radius,
      Math.sin(theta) * r * radius,
    ]);
  }
  return points;
}

// Map a market cap (USD) to a node radius via a cube-root scale (volume ~ cap),
// clamped so the smallest stays visible and the largest doesn't dominate.
export function capToRadius(cap: number | null): number {
  const floor = 0.35;
  if (!cap || cap <= 0) return floor;
  const t = Math.cbrt(cap / 1e12); // ~1 at $1T
  return Math.min(2.4, Math.max(floor, 0.5 * t + floor));
}
