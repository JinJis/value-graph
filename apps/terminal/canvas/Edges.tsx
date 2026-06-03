// [M5-FLOW-02] SUPPLIES edges as instanced cylinders (thickness = trade value) with
// a pooled Points cloud flowing supplier->customer. Two draw calls total -> 60fps.
// Confidence/freshness styling (solid/dashed/ghost, freshness dots) is M5-ENCODE-04.

import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import {
  AdditiveBlending,
  type BufferGeometry,
  InstancedMesh,
  Object3D,
  Quaternion,
  Vector3,
} from "three";

import {
  buildEdges,
  maxTradeValue,
  ParticlePool,
  valueToRadius,
} from "./edges";
import type { Vec3 } from "./layout";
import type { GraphEdge } from "./types";

const UP = new Vector3(0, 1, 0);
const dir = new Vector3();
const mid = new Vector3();
const quat = new Quaternion();
const obj = new Object3D();

export function Edges({
  edges,
  positions,
}: {
  edges: GraphEdge[];
  positions: Map<string, Vec3>;
}) {
  const lines = useMemo(() => buildEdges(edges, positions), [edges, positions]);
  const maxValue = useMemo(() => maxTradeValue(lines), [lines]);
  const pool = useMemo(() => new ParticlePool(lines.length), [lines]);

  const cylinders = useRef<InstancedMesh>(null);
  const flowGeom = useRef<BufferGeometry>(null);

  // Orient one unit cylinder (Y-up) per edge from supplier to customer. Static.
  useLayoutEffect(() => {
    const mesh = cylinders.current;
    if (!mesh) return;
    for (let i = 0; i < lines.length; i++) {
      const { a, b, value } = lines[i];
      const va = new Vector3(...a);
      const vb = new Vector3(...b);
      dir.subVectors(vb, va);
      const len = dir.length() || 1e-6;
      mid.addVectors(va, vb).multiplyScalar(0.5);
      quat.setFromUnitVectors(UP, dir.clone().normalize());
      const radius = valueToRadius(value, maxValue);
      obj.position.copy(mid);
      obj.quaternion.copy(quat);
      obj.scale.set(radius, len, radius);
      obj.updateMatrix();
      mesh.setMatrixAt(i, obj.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }, [lines, maxValue]);

  // Advance the pooled flow particles each frame (clamp dt so tab-switches don't jump).
  useFrame((_, delta) => {
    pool.update(lines, Math.min(delta, 0.05));
    if (flowGeom.current) {
      flowGeom.current.attributes.position.needsUpdate = true;
    }
  });

  if (lines.length === 0) return null;

  return (
    <group>
      <instancedMesh
        ref={cylinders}
        args={[undefined, undefined, lines.length]}
        frustumCulled={false}
      >
        <cylinderGeometry args={[1, 1, 1, 6]} />
        <meshStandardMaterial
          color="#33507a"
          transparent
          opacity={0.4}
          metalness={0}
          roughness={0.9}
        />
      </instancedMesh>

      <points key={pool.count} frustumCulled={false}>
        <bufferGeometry ref={flowGeom}>
          <bufferAttribute
            attach="attributes-position"
            args={[pool.positions, 3]}
            count={pool.count}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.16}
          sizeAttenuation
          color="#8fd0ff"
          transparent
          opacity={0.9}
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </group>
  );
}
