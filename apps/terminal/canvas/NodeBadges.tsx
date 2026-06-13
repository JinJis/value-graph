// On-canvas company identity: a camera-facing badge per node — logo (or colored monogram)
// + name + market cap — so the value chain reads at a glance instead of being unlabeled
// spheres. All WebGL (drei <Billboard>/<Text> + textured meshes), never DOM nodes.
//
// Badges are billboarded and few (one per *visible* company; on selection, only the selected
// node + its trade partners), so the per-node mesh cost stays well within budget. Logos load
// from a public CDN with a graceful monogram fallback (see ./logos).

import { Billboard, Text } from "@react-three/drei";
import { type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import { SRGBColorSpace, type Texture, TextureLoader } from "three";

import { useSelection } from "./controls";
import { capToRadius, type Vec3 } from "./layout";
import { initials, logoCandidates, monogramColor } from "./logos";
import { formatMarketCap } from "./marketFeed";
import type { MarketFeed } from "./marketFeed";
import type { GraphCompany } from "./types";

const BG = "#0a0e16"; // outline color, matches the canvas background for legible text

// Try each logo URL in turn; resolve to the first that loads, else null (monogram fallback).
function useLogoTexture(candidates: string[]): Texture | null {
  const [tex, setTex] = useState<Texture | null>(null);
  const key = candidates.join("|");
  useEffect(() => {
    let cancelled = false;
    let loaded: Texture | null = null;
    setTex(null);
    const list = key ? key.split("|") : [];
    const loader = new TextureLoader();
    loader.setCrossOrigin("anonymous");
    let i = 0;
    const tryNext = () => {
      if (cancelled || i >= list.length) return;
      const url = list[i++];
      loader.load(
        url,
        (t) => {
          if (cancelled) {
            t.dispose();
            return;
          }
          t.colorSpace = SRGBColorSpace;
          loaded = t;
          setTex(t);
        },
        undefined,
        () => tryNext(), // 404 / CORS / network -> next candidate
      );
    };
    tryNext();
    return () => {
      cancelled = true;
      loaded?.dispose();
    };
  }, [key]);
  return tex;
}

function NodeBadge({
  company,
  position,
  cap,
  emphasized,
  faded,
}: {
  company: GraphCompany;
  position: Vec3;
  cap: number | null;
  emphasized: boolean;
  faded: boolean;
}) {
  const toggle = useSelection((s) => s.toggle);
  const candidates = useMemo(() => logoCandidates(company), [company]);
  const tex = useLogoTexture(candidates);

  const chipR = 0.5;
  const radius = capToRadius(cap);
  const scale = emphasized ? 1.25 : 1;
  const opacity = faded ? 0.35 : 1;
  const color = monogramColor(company.ticker);

  return (
    <Billboard position={position}>
      <group
        position={[0, radius + 0.95, 0]}
        scale={scale}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          toggle(company.ticker);
        }}
      >
        {/* chip background — white behind a logo, the accent color behind a monogram */}
        <mesh>
          <circleGeometry args={[chipR, 40]} />
          <meshBasicMaterial
            color={tex ? "#ffffff" : color}
            transparent
            opacity={opacity}
            toneMapped={false}
          />
        </mesh>
        {tex ? (
          <mesh position={[0, 0, 0.01]}>
            <planeGeometry args={[chipR * 1.3, chipR * 1.3]} />
            <meshBasicMaterial
              map={tex}
              transparent
              opacity={opacity}
              toneMapped={false}
            />
          </mesh>
        ) : (
          <Text
            position={[0, 0, 0.01]}
            fontSize={chipR * 0.8}
            color="#ffffff"
            fillOpacity={opacity}
            anchorX="center"
            anchorY="middle"
          >
            {initials(company.name, company.ticker)}
          </Text>
        )}

        <Text
          position={[0, -chipR - 0.34, 0]}
          fontSize={0.4}
          color={emphasized ? "#ffffff" : "#dbe4f3"}
          fillOpacity={opacity}
          anchorX="center"
          anchorY="middle"
          maxWidth={6}
          outlineWidth={0.018}
          outlineColor={BG}
        >
          {company.name}
        </Text>
        <Text
          position={[0, -chipR - 0.74, 0]}
          fontSize={0.3}
          color="#8aa0c0"
          fillOpacity={opacity}
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.014}
          outlineColor={BG}
        >
          {formatMarketCap(cap)}
        </Text>
      </group>
    </Billboard>
  );
}

export function NodeBadges({
  companies,
  positions,
  feed,
  badgeTickers,
  selected,
  neighbors,
}: {
  companies: GraphCompany[];
  positions: Map<string, Vec3>;
  feed: MarketFeed;
  badgeTickers: Set<string>;
  selected: string | null;
  neighbors: Set<string> | null;
}) {
  return (
    <group>
      {companies.map((c) => {
        if (!badgeTickers.has(c.ticker)) return null;
        const pos = positions.get(c.ticker);
        if (!pos) return null;
        const lit = !neighbors || neighbors.has(c.ticker);
        return (
          <NodeBadge
            key={c.ticker}
            company={c}
            position={pos}
            cap={c.market_cap ?? feed.marketCap(c.ticker)}
            emphasized={selected === c.ticker}
            faded={!lit}
          />
        );
      })}
    </group>
  );
}
