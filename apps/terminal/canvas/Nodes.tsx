// [M5-CANVAS-01] Company nodes as a single INSTANCED mesh (never DOM nodes).
// Size binds to the market feed; radius eases toward its target each frame (lerp,
// don't snap) so live-cap updates animate smoothly. Hundreds of instances = one
// draw call -> 60fps.

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import { Color, InstancedMesh, MathUtils, Object3D } from "three";

import { capToRadius, fibonacciSphere } from "./layout";
import type { MarketFeed } from "./marketFeed";
import type { GraphCompany } from "./types";

const NODE_COLOR = new Color("#5ea0ff");
const dummy = new Object3D();

export function Nodes({
  companies,
  feed,
  radius = 12,
}: {
  companies: GraphCompany[];
  feed: MarketFeed;
  radius?: number;
}) {
  const ref = useRef<InstancedMesh>(null);

  const { positions, targets } = useMemo(() => {
    const positions = fibonacciSphere(companies.length, radius);
    const targets = companies.map((c) =>
      capToRadius(c.market_cap ?? feed.marketCap(c.ticker)),
    );
    return { positions, targets };
  }, [companies, feed, radius]);

  // Per-instance current radius, eased toward `targets` (lerp, not snap).
  const current = useRef<number[]>([]);
  if (current.current.length !== companies.length) {
    current.current = targets.map((t) => t * 0.01); // grow in from ~0
  }

  useFrame(() => {
    const mesh = ref.current;
    if (!mesh) return;
    for (let i = 0; i < companies.length; i++) {
      current.current[i] = MathUtils.lerp(current.current[i], targets[i], 0.12);
      const [x, y, z] = positions[i];
      dummy.position.set(x, y, z);
      const s = current.current[i];
      dummy.scale.set(s, s, s);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  // Static per-instance colour (edges carry the confidence encoding in M5-ENCODE-04).
  useMemo(() => {
    const mesh = ref.current;
    if (!mesh) return;
    for (let i = 0; i < companies.length; i++) {
      mesh.setColorAt(i, NODE_COLOR);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [companies.length]);

  if (companies.length === 0) return null;

  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, companies.length]}
      frustumCulled={false}
      onUpdate={(m: InstancedMesh) => {
        // Seed identity matrices so nothing flashes at the origin pre-first-frame.
        for (let i = 0; i < companies.length; i++) {
          const [x, y, z] = positions[i];
          dummy.position.set(x, y, z);
          dummy.scale.setScalar(0.01);
          dummy.updateMatrix();
          m.setMatrixAt(i, dummy.matrix);
        }
        m.instanceMatrix.needsUpdate = true;
      }}
    >
      <sphereGeometry args={[1, 16, 16]} />
      <meshStandardMaterial metalness={0.1} roughness={0.5} />
    </instancedMesh>
  );
}
