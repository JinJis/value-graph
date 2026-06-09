"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  applyProgEvent,
  BlueprintProgress,
  type Prog,
} from "../../../../components/Progress";
import { useResumableRun } from "../../../../components/useResumableRun";
import { StepFooter } from "../../../../components/WorkflowSteps";
import {
  cancelTask,
  getBlueprint,
  listFinancials,
  putFinancials,
  researchFinancialsStream,
  type BlueprintCompany,
  type CveRunEvent,
} from "../../../../lib/api";

const EMPTY_PROG: Prog = { output: "", steps: [], done: false, running: false };

// Editable fields -> the CVE cost buckets they feed (revenue + COGS/CAPEX/R&D/SG&A).
const FIELDS = [
  { key: "revenue", label: "Revenue" },
  { key: "cogs", label: "COGS" },
  { key: "capex", label: "CAPEX" },
  { key: "rnd", label: "R&D" },
  { key: "sga", label: "SG&A" },
] as const;

type FieldKey = (typeof FIELDS)[number]["key"];
type Draft = Record<FieldKey, string> & {
  currency: string;
  as_of_date: string;
  source: string;
};

const EMPTY_DRAFT: Draft = {
  revenue: "",
  cogs: "",
  capex: "",
  rnd: "",
  sga: "",
  currency: "",
  as_of_date: "",
  source: "",
};

// Fallback reporting currency by listing country, used to pre-fill the column until Deep
// Research (or the admin) confirms it. Figures are always in millions of THIS currency.
const COUNTRY_CURRENCY: Record<string, string> = {
  "United States": "USD",
  USA: "USD",
  US: "USD",
  Japan: "JPY",
  "South Korea": "KRW",
  Korea: "KRW",
  Taiwan: "TWD",
  China: "CNY",
  "Hong Kong": "HKD",
  Germany: "EUR",
  France: "EUR",
  Netherlands: "EUR",
  Ireland: "EUR",
  "United Kingdom": "GBP",
  UK: "GBP",
  Switzerland: "CHF",
  Canada: "CAD",
  India: "INR",
};

const guessCurrency = (country?: string | null): string =>
  (country && COUNTRY_CURRENCY[country.trim()]) || "";

const isHttpUrl = (s: string): boolean => /^https?:\/\//i.test(s.trim());

// Short host label for a citation URL (used in the live step list).
const hostOf = (s: string): string => {
  try {
    return new URL(s).hostname.replace(/^www\./, "");
  } catch {
    return s;
  }
};

const numOrNull = (s: string): number | null => {
  const t = s.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

export default function FinancialsPage() {
  const params = useParams<{ id: string }>();
  const themeId = params.id;

  const [companies, setCompanies] = useState<BlueprintCompany[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [researching, setResearching] = useState(false);
  const [researchingTicker, setResearchingTicker] = useState<string | null>(
    null,
  );
  const [prog, setProg] = useState<Prog>(EMPTY_PROG);
  const panelRef = useRef<HTMLDivElement>(null);

  // The live panel sits at the top; a per-company Research button is down in the table — so
  // scroll the panel into view when a run starts so its streaming progress is actually seen.
  useEffect(() => {
    if (prog.running)
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    else setResearchingTicker(null); // clear the company label once the run ends
  }, [prog.running]);

  const numStr = (v: unknown): string | null =>
    typeof v === "number" ? String(v) : typeof v === "string" ? v : null;

  function onResearchEvent(e: CveRunEvent) {
    setProg((p) => applyProgEvent(p, e)); // generic live progress (model, 💭, chunk, …)
    if (e.event === "task") {
      // (re)attached — name the company being researched from the task kind, if scoped.
      const kind = String(e.kind ?? "");
      const prefix = "financials-research:";
      setResearchingTicker(
        kind.startsWith(prefix) ? kind.slice(prefix.length) : null,
      );
    }
    if (e.event !== "filled") return;
    const t = String(e.ticker);
    setDrafts((d) => {
      const cur = d[t] ?? EMPTY_DRAFT;
      return {
        ...d,
        [t]: {
          revenue: numStr(e.revenue) ?? cur.revenue,
          cogs: numStr(e.cogs) ?? cur.cogs,
          capex: numStr(e.capex) ?? cur.capex,
          rnd: numStr(e.rnd) ?? cur.rnd,
          sga: numStr(e.sga) ?? cur.sga,
          currency: numStr(e.currency) ?? cur.currency,
          as_of_date: numStr(e.as_of_date) ?? cur.as_of_date,
          source: numStr(e.source) ?? cur.source,
        },
      };
    });
    setProg((p) => ({
      ...p,
      steps: [
        ...p.steps,
        {
          label: `filled ${t}`,
          detail:
            `revenue ${e.revenue ?? "—"} · cogs ${e.cogs ?? "—"}` +
            (e.source ? ` · src ${hostOf(String(e.source))}` : ""),
          tone: "ok",
        },
      ],
    }));
  }

  // `tickers` undefined -> research all; a single-element array -> just that company.
  async function onResearch(tickers?: string[]) {
    setResearching(true);
    if (tickers?.length === 1) setResearchingTicker(tickers[0]);
    setProg({ ...EMPTY_PROG, running: true });
    try {
      await researchFinancialsStream(themeId, onResearchEvent, tickers);
      await load();
    } catch (e) {
      setProg((p) => ({ ...p, running: false, error: String(e) }));
    } finally {
      setResearching(false);
      setResearchingTicker(null);
    }
  }

  // Resume a financials research already running for this theme.
  const { resuming } = useResumableRun(
    themeId,
    ["financials-research"],
    onResearchEvent,
  );
  const busy = researching || resuming;

  async function load() {
    try {
      const bp = await getBlueprint(themeId);
      const list = bp?.blueprint.companies ?? [];
      setCompanies(list);
      const tickers = list.map((c) => c.ticker);
      const fin = tickers.length ? await listFinancials(tickers) : [];
      const next: Record<string, Draft> = {};
      for (const c of list)
        next[c.ticker] = { ...EMPTY_DRAFT, currency: guessCurrency(c.country) };
      for (const f of fin) {
        const c = list.find((x) => x.ticker === f.company_ticker);
        next[f.company_ticker] = {
          revenue: f.revenue?.toString() ?? "",
          cogs: f.cogs?.toString() ?? "",
          capex: f.capex?.toString() ?? "",
          rnd: f.rnd?.toString() ?? "",
          sga: f.sga?.toString() ?? "",
          currency: f.currency ?? guessCurrency(c?.country),
          as_of_date: f.as_of_date ?? "",
          source: f.source ?? "",
        };
      }
      setDrafts(next);
      setError(null);
    } catch (e) {
      setError(`Load failed: ${String(e)}`);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId]);

  function setField(ticker: string, key: keyof Draft, value: string) {
    setDrafts((d) => ({
      ...d,
      [ticker]: { ...(d[ticker] ?? EMPTY_DRAFT), [key]: value },
    }));
  }

  async function onSave(ticker: string) {
    const d = drafts[ticker] ?? EMPTY_DRAFT;
    setSaving(ticker);
    setSaved(null);
    try {
      await putFinancials(ticker, {
        revenue: numOrNull(d.revenue),
        cogs: numOrNull(d.cogs),
        capex: numOrNull(d.capex),
        rnd: numOrNull(d.rnd),
        sga: numOrNull(d.sga),
        currency: d.currency.trim().toUpperCase() || null,
        as_of_date: d.as_of_date.trim() || null,
        source: d.source.trim() || null,
      });
      setSaved(ticker);
      setError(null);
    } catch (e) {
      setError(`Save failed for ${ticker}: ${String(e)}`);
    } finally {
      setSaving(null);
    }
  }

  return (
    <section>
      <h2 style={{ marginBottom: 4 }}>Financials</h2>
      <p style={{ color: "#475569" }}>
        <small>
          The complementary side of the CVE math: revenue + cost buckets let a
          supplier-side disclosure be cross-checked into a{" "}
          <strong>derived</strong> edge (instead of an estimate). Auto-fill with
          Deep Research, or enter values manually — then Save. All figures are
          in{" "}
          <strong>
            millions of each company&apos;s own reporting currency
          </strong>{" "}
          (the Currency column) — not converted to USD. Each researched figure
          cites the filing / IR page it came from in the <strong>Source</strong>{" "}
          column.
        </small>
      </p>

      <div style={{ margin: "0 0 12px" }}>
        <button
          type="button"
          onClick={() => void onResearch()}
          disabled={busy || companies.length === 0}
        >
          {busy && !researchingTicker
            ? "Researching all…"
            : "Auto-fill ALL with Deep Research"}
        </button>{" "}
        <small style={{ color: "#64748b" }}>
          Finds revenue + cost buckets per company (with citations) and fills
          the table; review and Save.
        </small>
        <div ref={panelRef}>
          <BlueprintProgress
            prog={prog}
            markdown
            onStop={(id) => void cancelTask(id)}
            labels={{
              running: researchingTicker
                ? `Researching ${researchingTicker}'s financials…`
                : "Researching financials…",
              done: "Financials researched",
              idle: "Financials research",
            }}
          />
        </div>
      </div>

      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {companies.length === 0 ? (
        <p>
          <small>
            No blueprint companies yet — generate a blueprint first.
          </small>
        </p>
      ) : (
        <table
          style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}
        >
          <thead>
            <tr>
              <th
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 6,
                }}
              >
                Company
              </th>
              {FIELDS.map((f) => (
                <th
                  key={f.key}
                  style={{
                    textAlign: "left",
                    borderBottom: "1px solid #ccc",
                    padding: 6,
                  }}
                >
                  {f.label}
                </th>
              ))}
              <th
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 6,
                }}
              >
                Currency
              </th>
              <th
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 6,
                }}
              >
                As of
              </th>
              <th
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 6,
                }}
              >
                Source
              </th>
              <th style={{ borderBottom: "1px solid #ccc", padding: 6 }} />
            </tr>
          </thead>
          <tbody>
            {companies.map((c) => {
              const d = drafts[c.ticker] ?? EMPTY_DRAFT;
              return (
                <tr key={c.ticker}>
                  <td style={{ padding: 6 }}>
                    <strong>{c.ticker}</strong>
                    <br />
                    <small style={{ color: "#64748b" }}>{c.name}</small>
                  </td>
                  {FIELDS.map((f) => (
                    <td key={f.key} style={{ padding: 6 }}>
                      <input
                        inputMode="decimal"
                        style={{ width: 90 }}
                        value={d[f.key]}
                        onChange={(e) =>
                          setField(c.ticker, f.key, e.target.value)
                        }
                      />
                    </td>
                  ))}
                  <td style={{ padding: 6 }}>
                    <input
                      style={{ width: 56, textTransform: "uppercase" }}
                      maxLength={3}
                      placeholder="USD"
                      value={d.currency}
                      onChange={(e) =>
                        setField(c.ticker, "currency", e.target.value)
                      }
                    />
                  </td>
                  <td style={{ padding: 6 }}>
                    <input
                      type="date"
                      value={d.as_of_date}
                      onChange={(e) =>
                        setField(c.ticker, "as_of_date", e.target.value)
                      }
                    />
                  </td>
                  <td style={{ padding: 6 }}>
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 6 }}
                    >
                      <input
                        style={{ width: 200 }}
                        placeholder="https://… (filing / IR page)"
                        title={d.source || "Where these figures came from"}
                        value={d.source}
                        onChange={(e) =>
                          setField(c.ticker, "source", e.target.value)
                        }
                      />
                      {isHttpUrl(d.source) && (
                        <a
                          href={d.source}
                          target="_blank"
                          rel="noreferrer"
                          title={d.source}
                          style={{ fontSize: 13, whiteSpace: "nowrap" }}
                        >
                          ↗ open
                        </a>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: 6, whiteSpace: "nowrap" }}>
                    <button
                      type="button"
                      onClick={() => void onSave(c.ticker)}
                      disabled={saving === c.ticker}
                    >
                      {saving === c.ticker ? "Saving…" : "Save"}
                    </button>
                    {saved === c.ticker && (
                      <span style={{ color: "#15803d", marginLeft: 6 }}>✓</span>
                    )}{" "}
                    <button
                      type="button"
                      onClick={() => void onResearch([c.ticker])}
                      disabled={busy}
                      title={`Deep Research just ${c.ticker}'s financials`}
                      style={{ fontSize: 12 }}
                    >
                      {researchingTicker === c.ticker
                        ? "Researching…"
                        : "🔍 Research"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <StepFooter themeId={themeId} currentKey="financials" />
    </section>
  );
}
