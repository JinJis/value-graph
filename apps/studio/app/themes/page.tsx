"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { createTheme, listThemes, type Theme } from "../../lib/api";

export default function ThemesPage() {
  const [themes, setThemes] = useState<Theme[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tickers, setTickers] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setThemes(await listThemes());
      setError(null);
    } catch (e) {
      setError(`Could not load themes: ${String(e)}`);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await createTheme({
        name: name.trim(),
        description: description.trim() || undefined,
        seed_tickers: tickers
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setName("");
      setDescription("");
      setTickers("");
      await refresh();
    } catch (e) {
      setError(`Create failed: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{ maxWidth: 720, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <h1>ValueGraph Studio — Themes</h1>
      <p style={{ color: "#475569" }}>
        <small>
          Create a theme, then it guides you through Theme → Blueprint → Tickets
          → Financials → Build → Publish.
        </small>
      </p>

      <form
        onSubmit={onCreate}
        style={{ display: "grid", gap: 8, margin: "1.5rem 0" }}
      >
        <h2>New theme</h2>
        <input
          placeholder="Theme name (e.g. AI Data Centers)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          placeholder="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          placeholder="Seed tickers, comma-separated (optional)"
          value={tickers}
          onChange={(e) => setTickers(e.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create theme"}
        </button>
      </form>

      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <h2>Existing themes</h2>
      {themes.length === 0 ? (
        <p>No themes yet.</p>
      ) : (
        <ul>
          {themes.map((t) => (
            <li key={t.id}>
              <Link href={`/themes/${t.id}`}>{t.name}</Link>{" "}
              <small>
                ({t.status}, v{t.version})
              </small>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
