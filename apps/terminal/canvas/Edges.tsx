// [M5-FLOW-02 / M5-DEPTH-03 / M5-ENCODE-04] SUPPLIES edges: instanced cylinders whose
// width = trade value and COLOUR = confidence (verified solid-bright / derived /
// estimated ghost-faint), a confidence-coloured flow cloud, and a freshness dot
// (green/amber/red) per edge. Depth toggles visibility per-instance (no re-mount).

import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import {
  AdditiveBlending,
  type BufferGeometry,
  Color,
  InstancedMesh,
  Object3D,
  Quaternion,
  Sphere,
  Vector3,
} from "three";

import {
  buildEdges,
  maxTradeValue,
  ParticlePool,
  valueToRadius,
} from "./edges";
import { confidenceStyle, freshnessColor } from "./encoding";
import { LAYOUT_RADIUS, type Vec3 } from "./layout";
import type { GraphEdge } from "./types";

const UP = new Vector3(0, 1, 0);
const dir = new Vector3();
const mid = new Vector3();
const quat = new Quaternion();
const obj = new Object3D();
const color = new Color();
const BOUNDS = new Sphere(new Vector3(0, 0, 0), LAYOUT_RADIUS + 2);

export function Edges({
  edges,
  positions,
  visibleEdges,
  particlesPerEdge = 6,
  radialSegments = 6,
  frustumCull = false,
}: {
  edges: GraphEdge[];
  positions: Map<string, Vec3>;
  visibleEdges: boolean[];
  particlesPerEdge?: number;
  radialSegments?: number;
  frustumCull?: boolean;
}) {
  const lines = useMemo(() => buildEdges(edges, positions), [edges, positions]);
  const maxValue = useMemo(() => maxTradeValue(lines), [lines]);
  const pool = useMemo(
    () => new ParticlePool(lines.length, particlesPerEdge),
    [lines, particlesPerEdge],
  );
  const particleColors = useMemo(
    () => pool.colorBuffer((i) => confidenceStyle(lines[i].confidence).rgb),
    [pool, lines],
  );

  const cylinders = useRef<InstancedMesh>(null);
  const dots = useRef<InstancedMesh>(null);
  const flowGeom = useRef<BufferGeometry>(null);

  // Orient + colour each edge; hidden edges collapse to scale 0. Freshness dot at mid.
  useLayoutEffect(() => {
    const tube = cylinders.current;
    const dot = dots.current;
    if (!tube || !dot) return;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const shown = visibleEdges[i];
      const style = confidenceStyle(line.confidence);
      const va = new Vector3(...line.a);
      const vb = new Vector3(...line.b);
      dir.subVectors(vb, va);
      const len = dir.length() || 1e-6;
      mid.addVectors(va, vb).multiplyScalar(0.5);
      quat.setFromUnitVectors(UP, dir.clone().normalize());

      const radius = shown
        ? valueToRadius(line.value, maxValue) * style.radiusScale
        : 0;
      obj.position.copy(mid);
      obj.quaternion.copy(quat);
      obj.scale.set(radius, shown ? len : 0, radius);
      obj.updateMatrix();
      tube.setMatrixAt(i, obj.matrix);
      tube.setColorAt(i, color.set(style.colorHex));

      // Freshness dot sits at the edge midpoint.
      obj.quaternion.identity();
      obj.scale.setScalar(shown ? 0.18 : 0);
      obj.updateMatrix();
      dot.setMatrixAt(i, obj.matrix);
      dot.setColorAt(i, color.set(freshnessColor(line.freshness)));
    }
    tube.instanceMatrix.needsUpdate = true;
    if (tube.instanceColor) tube.instanceColor.needsUpdate = true;
    tube.boundingSphere = BOUNDS;
    dot.instanceMatrix.needsUpdate = true;
    if (dot.instanceColor) dot.instanceColor.needsUpdate = true;
    dot.boundingSphere = BOUNDS;
  }, [lines, maxValue, visibleEdges]);

  // Advance pooled flow particles each frame (clamp dt so tab-switches don't jump).
  useFrame((_, delta) => {
    pool.update(lines, Math.min(delta, 0.05), visibleEdges);
    if (flowGeom.current)
      flowGeom.current.attributes.position.needsUpdate = true;
  });

  if (lines.length === 0) return null;

  return (
    <group>
      <instancedMesh
        ref={cylinders}
        args={[undefined, undefined, lines.length]}
        frustumCulled={frustumCull}
      >
        <cylinderGeometry args={[1, 1, 1, radialSegments]} />
        <meshStandardMaterial
          transparent
          opacity={0.55}
          metalness={0}
          roughness={0.9}
        />
      </instancedMesh>

      <instancedMesh
        ref={dots}
        args={[undefined, undefined, lines.length]}
        frustumCulled={frustumCull}
      >
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      <points key={pool.count} frustumCulled={false}>
        <bufferGeometry ref={flowGeom}>
          <bufferAttribute
            attach="attributes-position"
            args={[pool.positions, 3]}
            count={pool.count}
          />
          <bufferAttribute
            attach="attributes-color"
            args={[particleColors, 3]}
            count={pool.count}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.17}
          sizeAttenuation
          vertexColors
          transparent
          opacity={0.9}
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </group>
  );
}
