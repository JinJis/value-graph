// [M5-DEPTH-03] Supply-chain depth + level-of-detail. Depth is hop distance from the
// demand-side focal companies (customers that aren't themselves suppliers) walking
// UPSTREAM along customer->supplier; the depth slider reveals successively deeper
// tiers. Visibility is toggled per-instance (scale 0) — never a re-mount. Beyond
// ~1k nodes, LOD drops geometry detail and turns on whole-graph frustum culling.

import type { GraphCompany, GraphEdge } from "./types";

export const LOD_NODE_THRESHOLD = 1000;

export interface DepthIndex {
  depth: Map<string, number>; // ticker -> 1..maxDepth
  maxDepth: number;
}

// BFS depth from focal/demand roots, upstream along customer->supplier.
export function computeDepths(
  companies: GraphCompany[],
  edges: GraphEdge[],
): DepthIndex {
  const tickers = companies.map((c) => c.ticker);
  const suppliers = new Set(edges.map((e) => e.supplier));
  const customers = new Set(edges.map((e) => e.customer));

  // Reverse adjacency: from a customer, step to its suppliers (one tier deeper).
  const upstream = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const e of edges) {
    (
      upstream.get(e.customer) ?? upstream.set(e.customer, []).get(e.customer)!
    ).push(e.supplier);
    inDegree.set(e.customer, (inDegree.get(e.customer) ?? 0) + 1);
  }

  // Roots = demand sinks (customers that never supply). Fall back to most-supplied
  // nodes, then to everything (a graph with no edges).
  let roots = tickers.filter((t) => customers.has(t) && !suppliers.has(t));
  if (roots.length === 0 && edges.length > 0) {
    const max = Math.max(...inDegree.values());
    roots = [...inDegree.entries()]
      .filter(([, d]) => d === max)
      .map(([t]) => t);
  }
  if (roots.length === 0) roots = tickers;

  const depth = new Map<string, number>();
  let queue = roots.map((t) => ({ t, d: 1 }));
  for (const { t } of queue) depth.set(t, 1);
  while (queue.length > 0) {
    const next: { t: string; d: number }[] = [];
    for (const { t, d } of queue) {
      for (const s of upstream.get(t) ?? []) {
        if (!depth.has(s)) {
          depth.set(s, d + 1);
          next.push({ t: s, d: d + 1 });
        }
      }
    }
    queue = next;
  }

  const reachedMax = Math.max(1, ...depth.values());
  // Disconnected nodes appear only at full reveal (never permanently hidden).
  for (const t of tickers) if (!depth.has(t)) depth.set(t, reachedMax);

  return { depth, maxDepth: reachedMax };
}

// Per-company visibility (aligned to `companies` order) at a depth limit.
export function nodeVisibility(
  companies: GraphCompany[],
  depth: Map<string, number>,
  limit: number,
): boolean[] {
  return companies.map((c) => (depth.get(c.ticker) ?? 1) <= limit);
}

// An edge shows only when both endpoints are visible.
export function edgeVisibility(
  edges: GraphEdge[],
  depth: Map<string, number>,
  limit: number,
): boolean[] {
  return edges.map(
    (e) =>
      (depth.get(e.supplier) ?? 1) <= limit &&
      (depth.get(e.customer) ?? 1) <= limit,
  );
}

export interface LodProfile {
  sphereSegments: number;
  radialSegments: number;
  particlesPerEdge: number;
  frustumCull: boolean;
}

// Drop detail + enable frustum culling for large graphs (perf is an AC).
export function lodProfile(nodeCount: number): LodProfile {
  if (nodeCount > LOD_NODE_THRESHOLD) {
    return {
      sphereSegments: 8,
      radialSegments: 5,
      particlesPerEdge: 3,
      frustumCull: true,
    };
  }
  return {
    sphereSegments: 16,
    radialSegments: 6,
    particlesPerEdge: 6,
    frustumCull: false,
  };
}
