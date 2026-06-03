// [M5-NAV-05] Interaction: a tiny selection store + incidence helpers + camera config.
// Selecting a node lights its incident edges and immediate neighbours and dims the
// rest, so a company's trade relationships pop out. Picking empty space clears it.

import { create } from "zustand";

import type { GraphEdge } from "./types";

interface SelectionState {
  selected: string | null;
  select: (ticker: string | null) => void;
  toggle: (ticker: string) => void;
  clear: () => void;
}

export const useSelection = create<SelectionState>((set) => ({
  selected: null,
  select: (ticker) => set({ selected: ticker }),
  toggle: (ticker) =>
    set((s) => ({ selected: s.selected === ticker ? null : ticker })),
  clear: () => set({ selected: null }),
}));

// Per-edge "lit" mask: every edge when nothing is selected, else edges touching it.
export function incidentEdges(
  edges: GraphEdge[],
  selected: string | null,
): boolean[] {
  if (!selected) return edges.map(() => true);
  return edges.map((e) => e.supplier === selected || e.customer === selected);
}

// The selected node plus its direct trade partners (null when nothing is selected).
export function neighborhood(
  edges: GraphEdge[],
  selected: string | null,
): Set<string> | null {
  if (!selected) return null;
  const set = new Set<string>([selected]);
  for (const e of edges) {
    if (e.supplier === selected) set.add(e.customer);
    if (e.customer === selected) set.add(e.supplier);
  }
  return set;
}

// OrbitControls tuning for smooth, bounded navigation.
export const ORBIT = {
  dampingFactor: 0.08,
  minDistance: 8,
  maxDistance: 90,
  rotateSpeed: 0.6,
  zoomSpeed: 0.8,
  panSpeed: 0.6,
};
