"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { StepFooter } from "../../../components/WorkflowSteps";
import {
  listSources,
  sourceContentUrl,
  uploadSource,
  type Source,
} from "../../../lib/api";

const SOURCE_TYPES = ["filing", "IR", "report", "news", "interview"];

export default function ThemePage() {
  const { id: themeId } = useParams<{ id: string }>();
  const [sources, setSources] = useState<Source[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState("report");
  const [publisher, setPublisher] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setSources(await listSources(themeId));
      setError(null);
    } catch (e) {
      setError(`Could not load sources: ${String(e)}`);
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
    <section>
      <h2 style={{ marginBottom: 4 }}>Theme &amp; context</h2>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          Optionally add source documents (filings, IR decks, reports) for this
          theme, then move on to the blueprint. Sources here — and citations
          found later during research — all feed the graph’s provenance.
        </small>
      </p>

      <h3>Add context</h3>
      <form
        onSubmit={onUpload}
        style={{ display: "grid", gap: 8, maxWidth: 520 }}
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

      <h3>Sources ({sources.length})</h3>
      {sources.length === 0 ? (
        <p>
          <small>
            No sources yet (optional — you can generate a blueprint without
            them).
          </small>
        </p>
      ) : (
        <ul>
          {sources.map((s) => (
            <li key={s.id}>
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

      <StepFooter themeId={themeId} currentKey="theme" />
    </section>
  );
}
