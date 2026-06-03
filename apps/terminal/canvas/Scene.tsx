"use client";

// [M5-CANVAS-01] The WebGL macro map: a dark R3F canvas rendering Production
// companies as instanced node spheres sized by the market feed. Edges, depth,
// confidence/freshness encoding, and richer navigation land in M5-FLOW/DEPTH/
// ENCODE/NAV. OrbitControls here is the minimal "look around" until M5-NAV-05.

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";

import { Nodes } from "./Nodes";
import { mockMarketFeed } from "./marketFeed";
import type { PublishedGraph } from "./types";

const BACKGROUND = "#0a0e16";

export function Scene({ graph }: { graph: PublishedGraph }) {
  return (
    <Canvas
      camera={{ position: [0, 0, 34], fov: 50, near: 0.1, far: 200 }}
      dpr={[1, 2]}
      style={{ width: "100%", height: "100%", background: BACKGROUND }}
    >
      <color attach="background" args={[BACKGROUND]} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[10, 12, 8]} intensity={1.1} />
      <Nodes companies={graph.companies} feed={mockMarketFeed} />
      <OrbitControls enablePan enableZoom enableRotate makeDefault />
    </Canvas>
  );
}
