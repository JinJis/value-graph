"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  approveBlueprint,
  generateBlueprint,
  getBlueprint,
  getTheme,
  saveBlueprint,
  type BlueprintCompany,
  type Coverage,
  type Theme,
} from "../../../../lib/api";

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

  const onGenerate = () =>
    run(async () => {
      await generateBlueprint(themeId);
      await load();
    }, "Generate (needs GOOGLE_API_KEY)");

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
        <button type="button" onClick={onGenerate} disabled={busy}>
          Generate (DEEP)
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
