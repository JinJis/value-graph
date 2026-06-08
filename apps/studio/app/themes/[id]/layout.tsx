"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  STEP_DEFS,
  stepHref,
  WorkflowSteps,
  type StepStatus,
  type WorkflowStep,
} from "../../../components/WorkflowSteps";
import {
  getBlueprint,
  getPublishPreview,
  getTheme,
  getThemeQuality,
  listFinancials,
  listTasks,
  listTickets,
  type TaskInfo,
  type Theme,
} from "../../../lib/api";

// Which step a running task belongs to (for the activity chip's link).
const KIND_STEP: Record<string, string> = {
  "blueprint-generate": "/blueprint",
  "blueprint-refine": "/blueprint",
  "blueprint-discover": "/blueprint",
  "tickets-research": "/tickets",
  "financials-research": "/financials",
  "cve-run": "/build",
  "cve-research": "/build",
};

interface Signals {
  hasBlueprint: boolean;
  approved: boolean;
  tickets: number;
  financials: number;
  hasBuild: boolean;
  published: boolean;
}

const EMPTY: Signals = {
  hasBlueprint: false,
  approved: false,
  tickets: 0,
  financials: 0,
  hasBuild: false,
  published: false,
};

// Map a pathname to the current step key (e.g. /themes/x/tickets -> "tickets").
function currentKey(themeId: string, pathname: string): string {
  for (const step of [...STEP_DEFS].reverse()) {
    if (step.sub && pathname.startsWith(stepHref(themeId, step.sub)))
      return step.key;
  }
  return "theme";
}

function buildSteps(themeId: string, s: Signals): WorkflowStep[] {
  const need = (
    ok: boolean,
    hint: string,
  ): { status: StepStatus; hint?: string } =>
    ok ? { status: "available" } : { status: "locked", hint };
  const approvedHint = "Approve a blueprint first";

  const status: Record<string, { status: StepStatus; hint?: string }> = {
    theme: { status: "done" },
    blueprint: { status: s.hasBlueprint ? "done" : "available" },
    tickets: s.approved
      ? { status: s.tickets > 0 ? "done" : "available" }
      : { status: "locked", hint: approvedHint },
    financials: s.approved
      ? { status: s.financials > 0 ? "done" : "available" }
      : { status: "locked", hint: approvedHint },
    build: s.approved
      ? { status: s.hasBuild ? "done" : "available" }
      : { status: "locked", hint: approvedHint },
    publish: s.hasBuild
      ? { status: s.published ? "done" : "available" }
      : need(false, "Run Build first"),
  };

  return STEP_DEFS.map((def) => ({
    key: def.key,
    label: def.label,
    href: stepHref(themeId, def.sub),
    ...status[def.key],
  }));
}

export default function ThemeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const [theme, setTheme] = useState<Theme | null>(null);
  const [sig, setSig] = useState<Signals>(EMPTY);
  const [runningTasks, setRunningTasks] = useState<TaskInfo[]>([]);

  // Poll running tasks so the activity row + stepper reflect background runs even when
  // you're on another step (or just returned).
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const all = await listTasks(id);
        if (alive) setRunningTasks(all.filter((t) => t.status === "running"));
      } catch {
        /* ignore */
      }
    };
    void tick();
    const handle = setInterval(() => void tick(), 4000);
    return () => {
      alive = false;
      clearInterval(handle);
    };
  }, [id]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const t = await getTheme(id).catch(() => null);
      if (!alive) return;
      if (t) setTheme(t);
      const approved = t?.status === "approved";

      // Cheap (Postgres) signals first so the stepper renders without waiting on Neo4j.
      const [bp, tickets, quality] = await Promise.all([
        getBlueprint(id).catch(() => null),
        listTickets(id).catch(() => []),
        getThemeQuality(id).catch(() => null),
      ]);
      const tickers = bp?.blueprint.companies.map((c) => c.ticker) ?? [];
      const fin = tickers.length
        ? await listFinancials(tickers).catch(() => [])
        : [];
      if (!alive) return;
      setSig({
        hasBlueprint: !!bp,
        approved,
        tickets: tickets.length,
        financials: fin.length,
        hasBuild: false,
        published: !!quality,
      });

      // Build existence needs the graph store (Neo4j) — fetch last, tolerate failure.
      const preview = await getPublishPreview(id).catch(() => null);
      if (!alive) return;
      setSig((prev) => ({ ...prev, hasBuild: !!preview }));
    })();
    return () => {
      alive = false;
    };
    // runningTasks.length: re-derive step status when a background run starts/finishes.
  }, [id, pathname, runningTasks.length]);

  const key = currentKey(id, pathname);
  const steps = buildSteps(id, sig);

  return (
    <div
      style={{ maxWidth: 1040, margin: "1.5rem auto", fontFamily: "system-ui" }}
    >
      <p style={{ margin: 0 }}>
        <Link href="/themes">← All themes</Link>
      </p>
      <h1 style={{ margin: "8px 0 2px" }}>{theme ? theme.name : "Loading…"}</h1>
      {theme && (
        <p style={{ margin: 0, color: "#64748b" }}>
          <small>
            status: {theme.status} · v{theme.version}
            {theme.seed_tickers.length > 0 &&
              ` · seeds: ${theme.seed_tickers.join(", ")}`}
          </small>
        </p>
      )}
      <WorkflowSteps steps={steps} currentKey={key} />
      {runningTasks.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "center",
            margin: "-8px 0 16px",
          }}
        >
          <small style={{ color: "#64748b" }}>Running:</small>
          {runningTasks.map((t) => (
            <Link
              key={t.id}
              href={stepHref(id, KIND_STEP[t.kind] ?? "")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                textDecoration: "none",
                fontSize: 12,
                padding: "2px 10px",
                borderRadius: 999,
                background: "#fef3c7",
                color: "#92400e",
                border: "1px solid #fcd34d",
              }}
            >
              <span style={{ color: "#d97706" }}>●</span> {t.label}…
            </Link>
          ))}
        </div>
      )}
      {children}
    </div>
  );
}
