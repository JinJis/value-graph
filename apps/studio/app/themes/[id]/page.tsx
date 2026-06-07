"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  getPublishPreview,
  getTheme,
  getThemeQuality,
  listSources,
  publishTheme,
  runThemeCve,
  sourceContentUrl,
  uploadSource,
  type PublishPreview,
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

// Staging -> Production publish (explicit human action). Shows completeness + every
// blocking validation issue; publishing past issues requires an override reason.
function PublishPanel({
  themeId,
  onPublished,
}: {
  themeId: string;
  onPublished: () => void;
}) {
  const [preview, setPreview] = useState<PublishPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [cveMsg, setCveMsg] = useState<string | null>(null);

  async function loadPreview() {
    setLoading(true);
    try {
      setPreview(await getPublishPreview(themeId));
      setPreviewError(null);
    } catch (e) {
      setPreviewError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId]);

  async function onRunCve() {
    setRunning(true);
    setCveMsg(null);
    try {
      const s = await runThemeCve(themeId);
      setCveMsg(
        `Built v${s.build_version}: ${s.publishable_edges} publishable · ` +
          `${s.ghost_edges} gap · ${s.estimated_edges} estimated ` +
          `(from ${s.documents_ingested} document(s), ${s.claims} claim(s)).`,
      );
      await loadPreview();
    } catch (e) {
      setCveMsg(`CVE run failed: ${String(e)}`);
    } finally {
      setRunning(false);
    }
  }

  async function onPublish() {
    if (!actor.trim()) {
      setMsg("Enter your name/email first.");
      return;
    }
    setPublishing(true);
    setMsg(null);
    try {
      const r = await publishTheme(themeId, actor.trim(), overrideReason);
      setMsg(
        `Published v${r.snapshot_version} — ${r.edges} relationships` +
          (r.overridden ? " (overridden)." : "."),
      );
      setOverrideReason("");
      await loadPreview();
      onPublished();
    } catch (e) {
      setMsg(`Publish failed: ${String(e)}`);
    } finally {
      setPublishing(false);
    }
  }

  const c = preview?.completeness;
  const canPublish = preview?.can_publish ?? false;
  const blocked = !!preview && !canPublish;

  return (
    <section style={{ margin: "1.5rem 0" }}>
      <h2 style={{ marginBottom: 4 }}>Publish</h2>

      <div style={{ margin: "0 0 12px" }}>
        <button
          type="button"
          onClick={() => void onRunCve()}
          disabled={running}
        >
          {running ? "Running CVE…" : "Run CVE (build the graph)"}
        </button>{" "}
        <small style={{ color: "#64748b" }}>
          Cross-verify the theme’s sources + tickets into a Staging build.
        </small>
        {cveMsg && (
          <p style={{ marginTop: 6, fontSize: 13 }}>
            <small>{cveMsg}</small>
          </p>
        )}
      </div>

      {loading ? (
        <p>
          <small>Checking publish readiness…</small>
        </p>
      ) : previewError ? (
        <p style={{ color: "crimson" }}>
          <small>Couldn’t check readiness: {previewError}</small>{" "}
          <button type="button" onClick={() => void loadPreview()}>
            Retry
          </button>
        </p>
      ) : !preview ? (
        <p>
          <small>No CVE build yet — run CVE before publishing.</small>
        </p>
      ) : (
        <>
          <p style={{ margin: "0 0 6px" }}>
            <small>
              Build v{preview.build_version} ·{" "}
              {Math.round((c?.completeness ?? 0) * 100)}% complete (
              {c?.publishable_edges}/{c?.total_edges} relationships · threshold{" "}
              {Math.round((c?.threshold ?? 0) * 100)}%)
            </small>
          </p>
          {canPublish ? (
            <p style={{ color: "#15803d", margin: "0 0 8px" }}>
              ✓ Ready to publish — every exposed figure is fully sourced.
            </p>
          ) : (
            <div style={{ margin: "0 0 8px" }}>
              <p style={{ color: "#b45309", margin: "0 0 4px" }}>
                {preview.gate.violations.length} issue(s) block a clean publish:
              </p>
              <ul
                style={{
                  margin: 0,
                  fontSize: 13,
                  maxHeight: 160,
                  overflow: "auto",
                }}
              >
                {preview.gate.violations.map((v, i) => (
                  <li key={i}>
                    <code>{v.edge}</code> · {v.field} — {v.detail}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ display: "grid", gap: 6, maxWidth: 480 }}>
            <input
              placeholder="Your name / email (recorded in the audit log)"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
            {blocked && (
              <input
                placeholder="Override reason (required to publish with issues)"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
              />
            )}
            <button
              type="button"
              onClick={() => void onPublish()}
              disabled={
                publishing ||
                !actor.trim() ||
                (blocked && !overrideReason.trim())
              }
            >
              {publishing
                ? "Publishing…"
                : blocked
                  ? "Publish with override"
                  : "Publish"}
            </button>
          </div>
        </>
      )}
      {msg && (
        <p style={{ marginTop: 8, fontSize: 13 }}>
          <small>{msg}</small>
        </p>
      )}
    </section>
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

      <PublishPanel themeId={themeId} onPublished={() => void refresh()} />

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
