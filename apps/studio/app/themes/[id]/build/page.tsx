"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { BuildDiagnostics } from "../../../../components/BuildDiagnostics";
import { EdgeSourcePanel } from "../../../../components/EdgeSourcePanel";
import {
  applyProgEvent,
  BlueprintProgress,
  type Prog,
} from "../../../../components/Progress";
import { useResumableRun } from "../../../../components/useResumableRun";
import { StepFooter } from "../../../../components/WorkflowSteps";
import {
  cancelTask,
  researchAndBuildStream,
  runThemeCveStream,
  type CveRunEvent,
} from "../../../../lib/api";

const EMPTY_PROG: Prog = { output: "", steps: [], done: false, running: false };

export default function BuildPage() {
  const { id: themeId } = useParams<{ id: string }>();
  const [running, setRunning] = useState(false);
  const [prog, setProg] = useState<Prog>(EMPTY_PROG);
  const [diagKey, setDiagKey] = useState(0); // bump to re-pull diagnostics after a run

  function onEvent(e: CveRunEvent) {
    setProg((p) => applyProgEvent(p, e)); // generic live progress (model, 💭, chunk, …)
    if (e.event === "persisted" || e.event === "done") setDiagKey((k) => k + 1);
    const step = (label: string, detail = "", tone?: "ok" | "warn" | "err") =>
      setProg((p) => ({ ...p, steps: [...p.steps, { label, detail, tone }] }));
    switch (e.event) {
      case "phase":
        step(e.phase === "research" ? "▼ Deep Research" : "▼ Build (CVE)");
        break;
      case "researched": {
        const found = Number(e.trades_found ?? e.trades ?? 0);
        const kept = Number(e.trades ?? 0);
        const dropped = Number(e.dropped_unknown_ticker ?? 0);
        const degraded = Number(e.degraded_no_source ?? 0);
        const drops = [
          dropped ? `${dropped} unknown ticker` : "",
          degraded ? `${degraded} no-source → qualitative` : "",
        ]
          .filter(Boolean)
          .join(", ");
        step(
          "researched",
          `${kept} usable trade(s) of ${found} found` +
            (drops ? ` (${drops})` : "") +
            ` · ${e.financials} financials · ${e.sources} source(s)`,
          found > 0 && kept === 0 ? "warn" : "ok",
        );
        break;
      }
      case "financials_missing":
        step(
          "financials missing",
          `${e.count} compan${e.count === 1 ? "y" : "ies"} still need revenue/COGS — ` +
            "fill them on the Financials step (per-company Research or manual entry)",
          "warn",
        );
        break;
      case "tickets_retired":
        step(
          "tickets cleaned up",
          `Closed ${e.count} stale financials/calendar ticket(s) — those are filled on ` +
            "their own steps, not via tickets",
          "ok",
        );
        break;
      case "start":
        step("ingest", `${e.documents} document(s) · ${e.companies} companies`);
        break;
      case "stage":
        step(`${e.stage} ${e.label}`, String(e.detail ?? ""));
        break;
      case "persisted":
        step(
          `persisted build v${e.build_version}`,
          `${e.publishable_edges} publishable · ${e.ghost_edges} gap · ` +
            `${e.estimated_edges} estimated`,
          "ok",
        );
        break;
    }
  }

  async function run(
    stream: (id: string, cb: (e: CveRunEvent) => void) => Promise<void>,
  ) {
    setRunning(true);
    setProg({ ...EMPTY_PROG, running: true });
    try {
      await stream(themeId, onEvent);
    } catch (e) {
      setProg((p) => ({ ...p, running: false, error: String(e) }));
    } finally {
      setRunning(false);
    }
  }

  // Resume a build already running for this theme (e.g. started, then navigated away).
  const { resuming } = useResumableRun(themeId, ["cve-run", "cve-research"], onEvent);
  const busy = running || resuming;

  return (
    <section>
      <h2 style={{ marginBottom: 4 }}>Build the graph (CVE)</h2>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          Cross-verify the theme into a Staging build. <strong>Research &amp; build</strong>{" "}
          uses Deep Research to gather supplier→customer trades + financials and seeds the
          pipeline; figures it can’t source become tickets. It <strong>reuses financials
          already on file</strong> (e.g. filled on the Financials step), so it only researches
          the companies still missing them — no duplicate spend. <strong>Run CVE only</strong>{" "}
          rebuilds from existing claims/financials without re-researching.
        </small>
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => void run(researchAndBuildStream)}
          disabled={busy}
        >
          {busy ? "Working…" : "Research & build"}
        </button>
        <button
          type="button"
          onClick={() => void run(runThemeCveStream)}
          disabled={busy}
        >
          Run CVE only
        </button>
      </div>

      <BlueprintProgress
        prog={prog}
        markdown
        onStop={(id) => void cancelTask(id)}
        labels={{
          running: "Researching & building…",
          done: "Build complete",
          idle: "CVE build",
        }}
      />

      {prog.done && !prog.error && (
        <p style={{ marginTop: 8 }}>
          ✓ Build ready —{" "}
          <Link href={`/themes/${themeId}/publish`}>review &amp; publish →</Link>
        </p>
      )}

      <BuildDiagnostics themeId={themeId} refreshKey={diagKey} />

      <EdgeSourcePanel themeId={themeId} refreshKey={diagKey} />

      <StepFooter themeId={themeId} currentKey="build" />
    </section>
  );
}
