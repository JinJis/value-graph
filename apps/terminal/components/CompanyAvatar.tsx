"use client";

// A company's logo as a rounded chip, with a colored monogram fallback — the DOM counterpart
// of the on-canvas badge, used in the drawer header + relationship rows so partners are
// recognizable at a glance. Tries each logo candidate in turn; on error, the monogram shows.

import { useMemo, useState } from "react";

import { initials, logoCandidates, monogramColor } from "../canvas/logos";
import type { GraphCompany } from "../canvas/types";

type CompanyLike = Pick<
  GraphCompany,
  "ticker" | "name" | "logo_url" | "domain"
>;

export function CompanyAvatar({
  company,
  size = 40,
}: {
  company: CompanyLike;
  size?: number;
}) {
  const candidates = useMemo(() => logoCandidates(company), [company]);
  const [idx, setIdx] = useState(0);
  const url = candidates[idx];
  const radius = Math.round(size * 0.28);

  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt=""
        width={size}
        height={size}
        onError={() => setIdx((i) => i + 1)}
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          objectFit: "contain",
          background: "#fff",
          padding: Math.round(size * 0.12),
          boxSizing: "border-box",
          flexShrink: 0,
        }}
      />
    );
  }
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: monogramColor(company.ticker),
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 700,
        fontSize: Math.round(size * 0.4),
        flexShrink: 0,
      }}
    >
      {initials(company.name, company.ticker)}
    </div>
  );
}
