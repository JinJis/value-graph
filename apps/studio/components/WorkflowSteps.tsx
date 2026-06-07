"use client";

import Link from "next/link";

// The ValueGraph build pipeline, in order. The Studio guides an admin through these
// steps; each is one page under /themes/[id]. Order matches the engine flow:
// Theme -> Blueprint -> Tickets -> Financials -> Build (CVE) -> Publish.

export interface StepDef {
  key: string;
  label: string;
  sub: string; // route suffix under /themes/[id]
}

export const STEP_DEFS: StepDef[] = [
  { key: "theme", label: "Theme", sub: "" },
  { key: "blueprint", label: "Blueprint", sub: "/blueprint" },
  { key: "tickets", label: "Tickets", sub: "/tickets" },
  { key: "financials", label: "Financials", sub: "/financials" },
  { key: "build", label: "Build", sub: "/build" },
  { key: "publish", label: "Publish", sub: "/publish" },
];

export const stepHref = (themeId: string, sub: string): string =>
  `/themes/${themeId}${sub}`;

export type StepStatus = "done" | "available" | "locked";

export interface WorkflowStep {
  key: string;
  label: string;
  href: string;
  status: StepStatus;
  hint?: string; // why it's locked (shown on hover)
}

const DOT: Record<StepStatus, { bg: string; fg: string; mark: string }> = {
  done: { bg: "#15803d", fg: "#fff", mark: "✓" },
  available: { bg: "#e2e8f0", fg: "#334155", mark: "" },
  locked: { bg: "#f1f5f9", fg: "#94a3b8", mark: "🔒" },
};

function StepChip({
  step,
  index,
  current,
}: {
  step: WorkflowStep;
  index: number;
  current: boolean;
}) {
  const d = DOT[step.status];
  return (
    <Link
      href={step.href}
      title={step.status === "locked" ? step.hint : undefined}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        textDecoration: "none",
        padding: "4px 10px",
        borderRadius: 999,
        border: current ? "1px solid #2563eb" : "1px solid transparent",
        background: current ? "#eff6ff" : "transparent",
        color: step.status === "locked" ? "#94a3b8" : "#0f172a",
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 22,
          height: 22,
          borderRadius: 999,
          fontSize: 12,
          fontWeight: 600,
          background: current && step.status !== "done" ? "#2563eb" : d.bg,
          color: current && step.status !== "done" ? "#fff" : d.fg,
        }}
      >
        {d.mark || index}
      </span>
      <span style={{ fontSize: 13, fontWeight: current ? 600 : 400 }}>
        {step.label}
      </span>
    </Link>
  );
}

export function WorkflowSteps({
  steps,
  currentKey,
}: {
  steps: WorkflowStep[];
  currentKey: string;
}) {
  return (
    <nav
      aria-label="workflow"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 2,
        alignItems: "center",
        margin: "12px 0 20px",
      }}
    >
      {steps.map((s, i) => (
        <span key={s.key} style={{ display: "flex", alignItems: "center" }}>
          {i > 0 && (
            <span style={{ width: 16, height: 2, background: "#cbd5e1" }} />
          )}
          <StepChip step={s} index={i + 1} current={s.key === currentKey} />
        </span>
      ))}
    </nav>
  );
}

// Prev / Next links at the bottom of a step page. Uses the static order only, so a
// page can render it without recomputing step status.
export function StepFooter({
  themeId,
  currentKey,
}: {
  themeId: string;
  currentKey: string;
}) {
  const i = STEP_DEFS.findIndex((s) => s.key === currentKey);
  const prev = i > 0 ? STEP_DEFS[i - 1] : null;
  const next = i >= 0 && i < STEP_DEFS.length - 1 ? STEP_DEFS[i + 1] : null;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        marginTop: 32,
        paddingTop: 16,
        borderTop: "1px solid #e2e8f0",
        fontSize: 14,
      }}
    >
      <span>
        {prev && <Link href={stepHref(themeId, prev.sub)}>← {prev.label}</Link>}
      </span>
      <span>
        {next && <Link href={stepHref(themeId, next.sub)}>{next.label} →</Link>}
      </span>
    </div>
  );
}
