"use client";

// [M5] The WebGL macro map: instanced nodes (sized by the market feed) + flowing,
// quality-encoded SUPPLIES edges + drawn "?" gaps. A depth limit toggles per-instance
// visibility (no re-mount); LOD/frustum culling kick in past ~1k nodes; selecting a
// node lights its edges/neighbours and dims the rest. (M5-NAV-05.)

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useMemo } from "react";

import { ORBIT, incidentEdges, neighborhood, useSelection } from "./controls";
import { edgeVisibility, lodProfile, nodeVisibility } from "./depth";
import { Edges } from "./Edges";
import { GhostEdges } from "./GhostEdges";
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
  const selected = useSelection((s) => s.selected);
  const clear = useSelection((s) => s.clear);

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

  // Selection highlight: lit edges (incident) + lit nodes (selected + neighbours).
  const litEdges = useMemo(
    () => incidentEdges(graph.edges, selected),
    [graph, selected],
  );
  const neighbors = useMemo(
    () => neighborhood(graph.edges, selected),
    [graph, selected],
  );
  const litNodes = useMemo(
    () => graph.companies.map((c) => !neighbors || neighbors.has(c.ticker)),
    [graph, neighbors],
  );

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
