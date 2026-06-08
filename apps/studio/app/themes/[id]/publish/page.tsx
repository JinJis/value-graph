"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { BuildDiagnostics } from "../../../../components/BuildDiagnostics";
import { StepFooter } from "../../../../components/WorkflowSteps";
import {
  getPublishPreview,
  getThemeQuality,
  publishTheme,
  type PublishPreview,
  type QualityReport,
} from "../../../../lib/api";

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
      <h3 style={{ marginBottom: 4 }}>Published data quality</h3>
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

export default function PublishPage() {
  const { id: themeId } = useParams<{ id: string }>();
  const [preview, setPreview] = useState<PublishPreview | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [p, q] = await Promise.all([
        getPublishPreview(themeId),
        getThemeQuality(themeId),
      ]);
      setPreview(p);
      setQuality(q);
      setPreviewError(null);
    } catch (e) {
      setPreviewError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeId]);

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
      await load();
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
    <section>
      <h2 style={{ marginBottom: 4 }}>Publish</h2>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          Publish the latest build to Production (read-only) for the Terminal.
          Every exposed figure must be fully sourced; issues block publish
          unless you override with a logged reason.
        </small>
      </p>

      {quality && <DataQualityMeter report={quality} />}

      <BuildDiagnostics themeId={themeId} />

      {loading ? (
        <p>
          <small>Checking publish readiness…</small>
        </p>
      ) : previewError ? (
        <p style={{ color: "crimson" }}>
          <small>Couldn’t check readiness: {previewError}</small>{" "}
          <button type="button" onClick={() => void load()}>
            Retry
          </button>
        </p>
      ) : !preview ? (
        <p>
          <small>No build yet — run Build before publishing.</small>
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

      <StepFooter themeId={themeId} currentKey="publish" />
    </section>
  );
}
