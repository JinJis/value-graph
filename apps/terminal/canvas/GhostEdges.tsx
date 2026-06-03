// [M5-ENCODE-04] Gaps are DRAWN, never omitted: each gap edge (a relationship we
// can't yet quantify) renders as a faint dashed connection with a WebGL "?" marker.
// Gap edges are few, so per-edge drei <Line>/<Text> is fine; depth toggles `visible`
// (no unmount). All WebGL — no DOM nodes.

import { Line, Text } from "@react-three/drei";
import { useMemo } from "react";

import { GHOST_COLOR } from "./encoding";
import type { Vec3 } from "./layout";
import type { GhostEdge } from "./types";

function midpoint(a: Vec3, b: Vec3): Vec3 {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}

export function GhostEdges({
  ghosts,
  positions,
  depth,
  depthLimit,
}: {
  ghosts: GhostEdge[];
  positions: Map<string, Vec3>;
  depth: Map<string, number>;
  depthLimit: number;
}) {
  const drawn = useMemo(() => {
    return ghosts
      .map((g) => {
        const a = positions.get(g.supplier);
        const b = positions.get(g.customer);
        if (!a || !b) return null;
        const visible =
          (depth.get(g.supplier) ?? 1) <= depthLimit &&
          (depth.get(g.customer) ?? 1) <= depthLimit;
        return {
          key: `${g.supplier}->${g.customer}`,
          a,
          b,
          mid: midpoint(a, b),
          visible,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
  }, [ghosts, positions, depth, depthLimit]);

  if (drawn.length === 0) return null;

  return (
    <group>
      {drawn.map((g) => (
        <group key={g.key} visible={g.visible}>
          <Line
            points={[g.a, g.b]}
            color={GHOST_COLOR}
            lineWidth={1}
            dashed
            dashSize={0.45}
            gapSize={0.3}
            transparent
            opacity={0.55}
          />
          <Text
            position={g.mid}
            fontSize={0.7}
            color={GHOST_COLOR}
            anchorX="center"
            anchorY="middle"
            outlineWidth={0}
          >
            ?
          </Text>
        </group>
      ))}
    </group>
  );
}
