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
  listTickets,
  type Theme,
} from "../../../lib/api";

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
  }, [id, pathname]);

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
      {children}
    </div>
  );
}
