"use client";

// [M5] The WebGL macro map: instanced nodes (sized by the market feed) + flowing,
// quality-encoded SUPPLIES edges + drawn "?" gaps. A depth limit toggles per-instance
// visibility (no re-mount); LOD/frustum culling kick in past ~1k nodes; selecting a
// node lights its edges/neighbours and dims the rest. (M5-NAV-05.)

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useMemo } from "react";

import {
  ORBIT,
  edgeKey,
  incidentEdges,
  neighborhood,
  useSelection,
} from "./controls";
import { edgeVisibility, lodProfile, nodeVisibility } from "./depth";
import { Edges } from "./Edges";
import { GhostEdges } from "./GhostEdges";
import { nodeLayout } from "./layout";
import { Nodes } from "./Nodes";
import { NodeBadges } from "./NodeBadges";
import { mockMarketFeed } from "./marketFeed";
import type { PublishedGraph } from "./types";

const BACKGROUND = "#0a0e16";

// Above this many visible nodes, labelling every one clutters the view — so badges show
// only for the selected node + its partners (the rest stay sized spheres until selected).
const BADGE_BUDGET = 70;

export function Scene({
  graph,
  depth,
  depthLimit,
}: {
  graph: PublishedGraph;
  depth: Map<string, number>;
  depthLimit: number;
}) {
  const selected = useSelection((s) => s.selected);
  const clear = useSelection((s) => s.clear);
  const highlightEdges = useSelection((s) => s.highlightEdges);

  // One shared {ticker -> position} map so nodes and edges agree.
  const positions = useMemo(
    () => nodeLayout(graph.companies.map((c) => c.ticker)),
    [graph],
  );
  const lod = useMemo(() => lodProfile(graph.companies.length), [graph]);

  // Per-instance visibility recomputed on each slider change (cheap -> < 100ms).
  const nodeVisible = useMemo(
    () => nodeVisibility(graph.companies, depth, depthLimit),
    [graph, depth, depthLimit],
  );
  const edgeVisible = useMemo(
    () => edgeVisibility(graph.edges, depth, depthLimit),
    [graph, depth, depthLimit],
  );

  // Selection highlight: a product click narrows to a specific edge set; otherwise the
  // selected node's incident edges (or all when nothing is selected).
  const litEdges = useMemo(() => {
    if (highlightEdges) {
      const set = new Set(highlightEdges);
      return graph.edges.map((e) => set.has(edgeKey(e.supplier, e.customer)));
    }
    return incidentEdges(graph.edges, selected);
  }, [graph, selected, highlightEdges]);
  const neighbors = useMemo(
    () => neighborhood(graph.edges, selected),
    [graph, selected],
  );
  const litNodes = useMemo(
    () => graph.companies.map((c) => !neighbors || neighbors.has(c.ticker)),
    [graph, neighbors],
  );

  // Which nodes get an identity badge (logo + name + cap). When something is selected, focus
  // on it + its partners; otherwise label every visible node, up to a clutter budget.
  const badgeTickers = useMemo(() => {
    if (selected) return neighbors ?? new Set([selected]);
    const visibleTickers = graph.companies
      .filter((_, i) => nodeVisible[i])
      .map((c) => c.ticker);
    return new Set(visibleTickers.length <= BADGE_BUDGET ? visibleTickers : []);
  }, [graph, selected, neighbors, nodeVisible]);

  return (
    <Canvas
      camera={{ position: [0, 0, 34], fov: 50, near: 0.1, far: 200 }}
      dpr={[1, 2]}
      style={{ width: "100%", height: "100%", background: BACKGROUND }}
      onPointerMissed={() => clear()}
    >
      <color attach="background" args={[BACKGROUND]} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[10, 12, 8]} intensity={1.1} />
      <Edges
        edges={graph.edges}
        positions={positions}
        visibleEdges={edgeVisible}
        litEdges={litEdges}
        particlesPerEdge={lod.particlesPerEdge}
        radialSegments={lod.radialSegments}
        frustumCull={lod.frustumCull}
      />
      <GhostEdges
        ghosts={graph.ghost_edges}
        positions={positions}
        depth={depth}
        depthLimit={depthLimit}
      />
      <Nodes
        companies={graph.companies}
        positions={positions}
        feed={mockMarketFeed}
        visible={nodeVisible}
        litNodes={litNodes}
        selected={selected}
        segments={lod.sphereSegments}
        frustumCull={lod.frustumCull}
      />
      <NodeBadges
        companies={graph.companies}
        positions={positions}
        feed={mockMarketFeed}
        badgeTickers={badgeTickers}
        selected={selected}
        neighbors={neighbors}
      />
      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={ORBIT.dampingFactor}
        minDistance={ORBIT.minDistance}
        maxDistance={ORBIT.maxDistance}
        rotateSpeed={ORBIT.rotateSpeed}
        zoomSpeed={ORBIT.zoomSpeed}
        panSpeed={ORBIT.panSpeed}
      />
    </Canvas>
  );
}
