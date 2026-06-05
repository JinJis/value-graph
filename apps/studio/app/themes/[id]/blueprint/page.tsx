"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  approveBlueprint,
  discoverBlueprintStream,
  generateBlueprintStream,
  getBlueprint,
  getTheme,
  refineBlueprintStream,
  saveBlueprint,
  type BlueprintCompany,
  type BlueprintEvent,
  type Coverage,
  type Theme,
} from "../../../../lib/api";
import { BlueprintProgress, type Prog } from "../../../../components/Progress";

const EMPTY_PROG: Prog = {
  output: "",
  steps: [],
  done: false,
  running: false,
};

interface EditCompany {
  ticker: string;
  name: string;
  country: string;
  exchange: string;
  role: string;
  products: string;
  required_data_points: string;
  source_url: string | null;
}

const EMPTY: EditCompany = {
  ticker: "",
  name: "",
  country: "",
  exchange: "",
  role: "",
  products: "",
  required_data_points: "",
  source_url: null,
};

const split = (s: string): string[] =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

function toEdit(c: BlueprintCompany): EditCompany {
  return {
    ticker: c.ticker,
    name: c.name,
    country: c.country,
    exchange: c.exchange ?? "",
    role: c.role,
    products: c.products.join(", "),
    required_data_points: c.required_data_points.join(", "),
    source_url: c.source_url,
  };
}

function fromEdit(e: EditCompany): BlueprintCompany {
  return {
    ticker: e.ticker,
    name: e.name,
    country: e.country,
    exchange: e.exchange || null,
    role: e.role,
    products: split(e.products),
    required_data_points: split(e.required_data_points),
    source_url: e.source_url,
  };
}

const FIELDS: (keyof EditCompany)[] = [
  "ticker",
  "name",
  "country",
  "exchange",
  "role",
  "products",
  "required_data_points",
];

export default function BlueprintReviewPage() {
  const params = useParams<{ id: string }>();
  const themeId = params.id;

  const [theme, setTheme] = useState<Theme | null>(null);
  const [companies, setCompanies] = useState<EditCompany[]>([]);
  const [relationshipTypes, setRelationshipTypes] = useState("");
  const [notes, setNotes] = useState("");
  const [version, setVersion] = useState<number | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [prog, setProg] = useState<Prog>(EMPTY_PROG);

  async function load() {
    try {
      setTheme(await getTheme(themeId));
      const bp = await getBlueprint(themeId);
      if (bp) {
        setCompanies(bp.blueprint.companies.map(toEdit));
        setRelationshipTypes(bp.blueprint.relationship_types.join(", "));
        setNotes(bp.blueprint.notes ?? "");
        setVersion(bp.blueprint.version);
        setCoverage(bp.coverage);
      }
      setError(null);
    } catch (e) {
      setError(`Load failed: ${String(e)}`);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId]);

  function updateCompany(
    index: number,
    field: keyof EditCompany,
    value: string,
  ) {
    setCompanies((cs) =>
      cs.map((c, i) => (i === index ? { ...c, [field]: value } : c)),
    );
  }

  function content() {
    return {
      companies: companies.filter((c) => c.ticker.trim()).map(fromEdit),
      relationship_types: split(relationshipTypes),
      notes: notes.trim() || null,
    };
  }

  async function run(action: () => Promise<void>, label: string) {
    setBusy(true);
    try {
      await action();
      setError(null);
    } catch (e) {
      setError(`${label} failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const onSave = () =>
    run(async () => {
      const r = await saveBlueprint(themeId, content());
      setVersion(r.blueprint.version);
      setCoverage(r.coverage);
    }, "Save");

  function onProgEvent(e: BlueprintEvent) {
    setProg((p) => {
      const next: Prog = { ...p };
      switch (e.event) {
        case "model":
          next.model = { tier: String(e.tier), model: String(e.model) };
          next.steps = [
            ...p.steps,
            { label: `Routed to ${e.tier} model ${e.model}`, tone: "ok" },
          ];
          break;
        case "endpoint":
          next.endpoint = {
            provider: String(e.provider),
            method: String(e.method),
          };
          break;
        case "prompt":
          next.prompt = String(e.text);
          next.steps = [
            ...p.steps,
            { label: `Built prompt (${e.chars} chars)` },
          ];
          break;
        case "llm_start":
          next.output = "";
          next.steps = [
            ...p.steps,
            { label: `Calling Gemini (attempt ${e.attempt}/${e.attempts})` },
          ];
          break;
        case "chunk":
          next.output = p.output + String(e.text);
          break;
        case "thought":
          next.steps = [
            ...p.steps,
            { label: `💭 ${String(e.text).slice(0, 200)}` },
          ];
          break;
        case "research":
          next.steps = [
            ...p.steps,
            {
              label: `${e.action === "read" ? "📄 Reading" : "🔎 Searching"}`,
              detail: String(e.detail).slice(0, 200),
            },
          ];
          break;
        case "parse":
          next.steps = [
            ...p.steps,
            {
              label: `Parse: ${e.status}`,
              detail: e.detail ? String(e.detail).slice(0, 160) : undefined,
              tone:
                e.status === "ok"
                  ? "ok"
                  : e.status === "retry"
                    ? "warn"
                    : "err",
            },
          ];
          break;
        case "round":
          next.steps = [...p.steps, { label: `Round ${e.round}/${e.cap}` }];
          break;
        case "merged":
          next.steps = [
            ...p.steps,
            {
              label: `Merged: +${e.added} new, ~${e.updated} updated (Δ${e.delta})`,
              detail: e.converged ? "converged" : undefined,
              tone: "ok",
            },
          ];
          break;
        case "sources":
          next.steps = [
            ...p.steps,
            { label: `Created ${e.created} source(s)`, tone: "ok" },
          ];
          break;
        case "note":
          next.steps = [...p.steps, { label: String(e.text), tone: "warn" }];
          break;
        case "validate":
          next.steps = [
            ...p.steps,
            {
              label:
                e.discovered !== undefined
                  ? `Discovered ${e.discovered} → +${e.added} new (${e.companies} total)`
                  : `Validated ${e.companies} companies`,
              tone: "ok",
            },
          ];
          break;
        case "saved":
          next.steps = [
            ...p.steps,
            { label: `Saved blueprint v${e.version}`, tone: "ok" },
          ];
          break;
        case "error":
          next.error = String(e.detail);
          next.running = false;
          break;
        case "done":
          next.done = true;
          next.running = false;
          break;
      }
      return next;
    });
  }

  function streamRun(
    stream: (id: string, cb: (e: BlueprintEvent) => void) => Promise<void>,
    label: string,
  ) {
    return run(async () => {
      setProg({ ...EMPTY_PROG, running: true });
      await stream(themeId, onProgEvent);
      setProg((p) => ({ ...p, running: false }));
      await load();
    }, label);
  }

  const onGenerate = () =>
    streamRun(generateBlueprintStream, "Generate (Deep Research)");
  const onRefine = () => streamRun(refineBlueprintStream, "Refine (DEEP)");
  const onDiscover = () =>
    streamRun(discoverBlueprintStream, "Discover (RESEARCH)");

  const onApprove = () =>
    run(async () => setTheme(await approveBlueprint(themeId)), "Approve");

  return (
    <main
      style={{ maxWidth: 1100, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <p>
        <Link href={`/themes/${themeId}`}>← Theme</Link>
      </p>
      <h1>Blueprint review</h1>
      <p>
        <small>
          {theme ? `${theme.name} · status: ${theme.status}` : "Loading…"}
          {version !== null && ` · blueprint v${version}`}
        </small>
      </p>

      <div style={{ display: "flex", gap: 8, margin: "1rem 0" }}>
        <button
          type="button"
          onClick={onGenerate}
          disabled={busy}
          title="First-pass generation via the Gemini Deep Research agent (web-cited)"
        >
          Generate (Deep Research)
        </button>
        <button
          type="button"
          onClick={onRefine}
          disabled={busy || version === null}
          title={version === null ? "Generate a blueprint first" : undefined}
        >
          Refine (DEEP)
        </button>
        <button
          type="button"
          onClick={onDiscover}
          disabled={busy || version === null}
          title={version === null ? "Generate a blueprint first" : undefined}
        >
          Discover (RESEARCH)
        </button>
        <button type="button" onClick={onSave} disabled={busy}>
          Save edits
        </button>
        <button type="button" onClick={onApprove} disabled={busy}>
          Approve → ticketing
        </button>
      </div>

      {coverage && (
        <p style={{ color: coverage.meets_threshold ? "green" : "darkorange" }}>
          Coverage: {coverage.company_count} companies · focus countries{" "}
          {coverage.focus_countries.join(", ") || "—"} ·{" "}
          {coverage.meets_threshold
            ? "meets bar"
            : "below bar (≥30, ≥4 countries)"}
        </p>
      )}
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <BlueprintProgress prog={prog} />

      <p>
        <label>
          Relationship types:{" "}
          <input
            value={relationshipTypes}
            onChange={(e) => setRelationshipTypes(e.target.value)}
            placeholder="SUPPLIES"
            style={{ width: 300 }}
          />
        </label>
      </p>

      <table
        style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}
      >
        <thead>
          <tr>
            {FIELDS.map((f) => (
              <th
                key={f}
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 4,
                }}
              >
                {f}
              </th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {companies.map((c, i) => (
            <tr key={i}>
              {FIELDS.map((f) => (
                <td key={f} style={{ padding: 2 }}>
                  <input
                    value={c[f] ?? ""}
                    onChange={(e) => updateCompany(i, f, e.target.value)}
                    style={{ width: "100%", boxSizing: "border-box" }}
                  />
                </td>
              ))}
              <td>
                <button
                  type="button"
                  onClick={() =>
                    setCompanies((cs) => cs.filter((_, j) => j !== i))
                  }
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        <button
          type="button"
          onClick={() => setCompanies((cs) => [...cs, { ...EMPTY }])}
        >
          + Add company
        </button>
      </p>

      <p>
        <label>
          Notes:
          <br />
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            style={{ width: "100%" }}
          />
        </label>
      </p>
    </main>
  );
}
