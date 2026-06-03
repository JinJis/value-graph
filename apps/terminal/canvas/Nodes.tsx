// [M5-CANVAS-01 / M5-NAV-05] Company nodes as a single INSTANCED mesh (never DOM
// nodes). Size binds to the market feed; radius eases toward target each frame (lerp,
// don't snap). Hundreds of instances = one draw call -> 60fps. Click selects a node
// (instanced raycast -> ticker); the selected node is highlighted + enlarged, its
// neighbours stay lit, the rest dim.

import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  Color,
  InstancedMesh,
  MathUtils,
  Object3D,
  Sphere,
  Vector3,
} from "three";

import { useSelection } from "./controls";
import { capToRadius, LAYOUT_RADIUS, type Vec3 } from "./layout";
import type { MarketFeed } from "./marketFeed";
import type { GraphCompany } from "./types";

const NODE_COLOR = new Color("#5ea0ff");
const SELECTED_COLOR = new Color("#e8f0ff");
const DIM_COLOR = new Color("#2a3346");
const dummy = new Object3D();
const BOUNDS = new Sphere(new Vector3(0, 0, 0), LAYOUT_RADIUS + 3);

export function Nodes({
  companies,
  positions,
  feed,
  visible,
  litNodes,
  selected,
  segments = 16,
  frustumCull = false,
}: {
  companies: GraphCompany[];
  positions: Map<string, Vec3>;
  feed: MarketFeed;
  visible: boolean[];
  litNodes: boolean[];
  selected: string | null;
  segments?: number;
  frustumCull?: boolean;
}) {
  const ref = useRef<InstancedMesh>(null);
  const toggle = useSelection((s) => s.toggle);

  const { points, targets } = useMemo(() => {
    const points = companies.map(
      (c) => positions.get(c.ticker) ?? ([0, 0, 0] as Vec3),
    );
    const targets = companies.map((c) =>
      capToRadius(c.market_cap ?? feed.marketCap(c.ticker)),
    );
    return { points, targets };
  }, [companies, positions, feed]);

  // Per-instance current radius, eased toward `targets` (lerp, not snap).
  const current = useRef<number[]>([]);
  if (current.current.length !== companies.length) {
    current.current = targets.map((t) => t * 0.01); // grow in from ~0
  }

  useFrame(() => {
    const mesh = ref.current;
    if (!mesh) return;
    for (let i = 0; i < companies.length; i++) {
      // Depth toggling + selection enlargement, both via the eased target (no re-mount).
      const grow = selected && companies[i].ticker === selected ? 1.4 : 1;
      const target = visible[i] ? targets[i] * grow : 0;
      current.current[i] = MathUtils.lerp(current.current[i], target, 0.18);
      const [x, y, z] = points[i];
      dummy.position.set(x, y, z);
      const s = current.current[i];
      dummy.scale.set(s, s, s);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  // Recolour on selection change: selected = bright, lit neighbours = normal, rest dim.
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    for (let i = 0; i < companies.length; i++) {
      const c =
        selected && companies[i].ticker === selected
          ? SELECTED_COLOR
          : litNodes[i]
            ? NODE_COLOR
            : DIM_COLOR;
      mesh.setColorAt(i, c);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [companies, litNodes, selected]);

  if (companies.length === 0) return null;

  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, companies.length]}
      frustumCulled={frustumCull}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        if (e.instanceId != null) toggle(companies[e.instanceId].ticker);
      }}
      onUpdate={(m: InstancedMesh) => {
        // Seed positions at ~0 scale so nothing flashes at the origin pre-first-frame.
        for (let i = 0; i < companies.length; i++) {
          const [x, y, z] = points[i];
          dummy.position.set(x, y, z);
          dummy.scale.setScalar(0.01);
          dummy.updateMatrix();
          m.setMatrixAt(i, dummy.matrix);
        }
        m.instanceMatrix.needsUpdate = true;
        m.boundingSphere = BOUNDS;
      }}
    >
      <sphereGeometry args={[1, segments, segments]} />
      <meshStandardMaterial metalness={0.1} roughness={0.5} />
    </instancedMesh>
  );
}
