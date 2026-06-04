"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  getTheme,
  getThemeQuality,
  listSources,
  sourceContentUrl,
  uploadSource,
  type QualityReport,
  type Source,
  type Theme,
} from "../../../lib/api";

const SOURCE_TYPES = ["filing", "IR", "report", "news", "interview"];

// verified / derived / estimated / gap — confidence-tier colours (CLAUDE.md §5).
const TIERS = [
  { key: "verified", label: "Verified", color: "#1b8a3a" },
  { key: "derived", label: "Derived", color: "#2f6fb0" },
  { key: "estimated", label: "Estimated", color: "#c98a00" },
  { key: "gap", label: "Gap", color: "#b03030" },
] as const;

function DataQualityMeter({ report }: { report: QualityReport }) {
  const q = report.quality;
  return (
    <div style={{ margin: "1rem 0" }}>
      <h2 style={{ marginBottom: 4 }}>Data quality</h2>
      <p style={{ margin: "0 0 8px" }}>
        <small>
          Published v{report.snapshot_version} · {report.total} relationships
        </small>
      </p>
      <div
        style={{
          display: "flex",
          height: 18,
          borderRadius: 4,
          overflow: "hidden",
          border: "1px solid #ddd",
        }}
      >
        {TIERS.map((t) => {
          const pct = q[t.key];
          return pct > 0 ? (
            <div
              key={t.key}
              title={`${t.label}: ${pct}%`}
              style={{ width: `${pct}%`, background: t.color }}
            />
          ) : null;
        })}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
        {TIERS.map((t) => (
          <small
            key={t.key}
            style={{ display: "flex", alignItems: "center", gap: 4 }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                background: t.color,
                display: "inline-block",
                borderRadius: 2,
              }}
            />
            {t.label} {q[t.key]}%
          </small>
        ))}
      </div>
    </div>
  );
}

export default function ThemeDetailPage() {
  const params = useParams<{ id: string }>();
  const themeId = params.id;

  const [theme, setTheme] = useState<Theme | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState("report");
  const [publisher, setPublisher] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [t, s, q] = await Promise.all([
        getTheme(themeId),
        listSources(themeId),
        getThemeQuality(themeId),
      ]);
      setTheme(t);
      setSources(s);
      setQuality(q);
      setError(null);
    } catch (e) {
      setError(`Could not load theme: ${String(e)}`);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId]);

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      await uploadSource(themeId, file, type, publisher.trim() || undefined);
      setFile(null);
      setPublisher("");
      await refresh();
    } catch (e) {
      setError(`Upload failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{ maxWidth: 720, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <p>
        <Link href="/themes">← All themes</Link>
      </p>
      <h1>{theme ? theme.name : "Loading…"}</h1>
      {theme && (
        <p>
          <small>
            {theme.status} · v{theme.version}
            {theme.seed_tickers.length > 0 &&
              ` · seeds: ${theme.seed_tickers.join(", ")}`}
          </small>
        </p>
      )}

      <p>
        <Link href={`/themes/${themeId}/blueprint`}>→ Review blueprint</Link>
        {" · "}
        <Link href={`/themes/${themeId}/tickets`}>→ Ticket queue</Link>
      </p>

      {quality ? (
        <DataQualityMeter report={quality} />
      ) : (
        <p>
          <small>Data quality appears here once the theme is published.</small>
        </p>
      )}

      <h2>Additional context</h2>
      <form
        onSubmit={onUpload}
        style={{ display: "grid", gap: 8, margin: "1rem 0" }}
      >
        <input
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {SOURCE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          placeholder="Publisher (optional)"
          value={publisher}
          onChange={(e) => setPublisher(e.target.value)}
        />
        <button type="submit" disabled={busy || !file}>
          {busy ? "Uploading…" : "Upload source"}
        </button>
      </form>

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {sources.length === 0 ? (
        <p>No sources uploaded yet.</p>
      ) : (
        <ul>
          {sources.map((s) => (
            <li key={s.id}>
              {/* Discovered citations are external URLs (no uploaded file); link to
                  the source itself. Uploaded files have no url, so serve their stored
                  content instead. */}
              <a
                href={s.url ?? sourceContentUrl(s)}
                target="_blank"
                rel="noreferrer"
              >
                {s.original_filename ?? s.url ?? s.id}
              </a>{" "}
              <small>
                ({s.type}
                {s.publisher ? ` · ${s.publisher}` : ""})
              </small>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
