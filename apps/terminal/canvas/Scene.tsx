"use client";

// [M5-CANVAS-01 / M5-FLOW-02 / M5-DEPTH-03] The WebGL macro map: a dark R3F canvas of
// instanced nodes (sized by the market feed) + flowing SUPPLIES edges. A depth limit
// toggles per-instance visibility (no re-mount); LOD/frustum culling kick in past ~1k
// nodes. Confidence/freshness encoding is M5-ENCODE-04; richer nav is M5-NAV-05.

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useMemo } from "react";

import { edgeVisibility, lodProfile, nodeVisibility } from "./depth";
import { Edges } from "./Edges";
import { nodeLayout } from "./layout";
import { Nodes } from "./Nodes";
import { mockMarketFeed } from "./marketFeed";
import type { PublishedGraph } from "./types";

const BACKGROUND = "#0a0e16";

export function Scene({
  graph,
  depth,
  depthLimit,
}: {
  graph: PublishedGraph;
  depth: Map<string, number>;
  depthLimit: number;
}) {
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

  return (
    <Canvas
      camera={{ position: [0, 0, 34], fov: 50, near: 0.1, far: 200 }}
      dpr={[1, 2]}
      style={{ width: "100%", height: "100%", background: BACKGROUND }}
    >
      <color attach="background" args={[BACKGROUND]} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[10, 12, 8]} intensity={1.1} />
      <Edges
        edges={graph.edges}
        positions={positions}
        visibleEdges={edgeVisible}
        particlesPerEdge={lod.particlesPerEdge}
        radialSegments={lod.radialSegments}
        frustumCull={lod.frustumCull}
      />
      <Nodes
        companies={graph.companies}
        positions={positions}
        feed={mockMarketFeed}
        visible={nodeVisible}
        segments={lod.sphereSegments}
        frustumCull={lod.frustumCull}
      />
      <OrbitControls enablePan enableZoom enableRotate makeDefault />
    </Canvas>
  );
}
