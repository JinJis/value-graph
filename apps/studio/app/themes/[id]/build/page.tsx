"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import {
  applyProgEvent,
  BlueprintProgress,
  type Prog,
} from "../../../../components/Progress";
import { useResumableRun } from "../../../../components/useResumableRun";
import { StepFooter } from "../../../../components/WorkflowSteps";
import {
  researchAndBuildStream,
  runThemeCveStream,
  type CveRunEvent,
} from "../../../../lib/api";

const EMPTY_PROG: Prog = { output: "", steps: [], done: false, running: false };

export default function BuildPage() {
  const { id: themeId } = useParams<{ id: string }>();
  const [running, setRunning] = useState(false);
  const [prog, setProg] = useState<Prog>(EMPTY_PROG);

  function onEvent(e: CveRunEvent) {
    setProg((p) => applyProgEvent(p, e)); // generic live progress (model, 💭, chunk, …)
    const step = (label: string, detail = "", tone?: "ok" | "warn" | "err") =>
      setProg((p) => ({ ...p, steps: [...p.steps, { label, detail, tone }] }));
    switch (e.event) {
      case "phase":
        step(e.phase === "research" ? "▼ Deep Research" : "▼ Build (CVE)");
        break;
      case "researched":
        step(
          "researched",
          `${e.trades} trade(s) · ${e.financials} financials · ${e.sources} source(s)`,
          "ok",
        );
        break;
      case "financial_tickets":
        step("financial tickets", `${e.opened} opened for missing figures`, "warn");
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
          pipeline; figures it can’t source become tickets. <strong>Run CVE only</strong>{" "}
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

      <StepFooter themeId={themeId} currentKey="build" />
    </section>
  );
}
