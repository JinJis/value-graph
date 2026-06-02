"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  getTheme,
  listSources,
  sourceContentUrl,
  uploadSource,
  type Source,
  type Theme,
} from "../../../lib/api";

const SOURCE_TYPES = ["filing", "IR", "report", "news", "interview"];

export default function ThemeDetailPage() {
  const params = useParams<{ id: string }>();
  const themeId = params.id;

  const [theme, setTheme] = useState<Theme | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState("report");
  const [publisher, setPublisher] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [t, s] = await Promise.all([
        getTheme(themeId),
        listSources(themeId),
      ]);
      setTheme(t);
      setSources(s);
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
      </p>

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
              <a href={sourceContentUrl(s)} target="_blank" rel="noreferrer">
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
