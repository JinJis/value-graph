"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  listPrompts,
  resetPrompt,
  setPrompt,
  type Prompt,
} from "../../lib/api";

// Edit any LLM / Deep Research prompt at runtime. Each prompt has a built-in default; saving
// an override persists it and the engine uses it on the next call. Reset reverts to default.

function PromptCard({
  prompt,
  onChange,
}: {
  prompt: Prompt;
  onChange: (p: Prompt) => void;
}) {
  const [draft, setDraft] = useState(prompt.effective);
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    setDraft(prompt.effective);
  }, [prompt.effective]);

  const dirty = draft !== prompt.effective;

  async function onSave() {
    setBusy("save");
    setMsg(null);
    try {
      onChange(await setPrompt(prompt.key, draft));
      setMsg("Saved ✓");
    } catch (e) {
      setMsg(`Save failed: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function onReset() {
    setBusy("reset");
    setMsg(null);
    try {
      const next = await resetPrompt(prompt.key);
      onChange(next);
      setDraft(next.effective);
      setMsg("Reset to default ✓");
    } catch (e) {
      setMsg(`Reset failed: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      style={{
        border: "1px solid #cbd5e1",
        borderRadius: 8,
        padding: "12px 16px",
        margin: "1rem 0",
        background: "#f8fafc",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <strong style={{ fontSize: 15 }}>{prompt.title}</strong>
        <code style={{ fontSize: 12, color: "#64748b" }}>{prompt.key}</code>
        {prompt.is_overridden && (
          <span
            style={{
              fontSize: 11,
              background: "#fde047",
              color: "#0f172a",
              borderRadius: 6,
              padding: "1px 8px",
            }}
          >
            overridden
          </span>
        )}
      </div>
      <p style={{ margin: "4px 0 8px", color: "#475569", fontSize: 13 }}>
        {prompt.description}
      </p>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={false}
        rows={Math.min(24, Math.max(6, draft.split("\n").length + 1))}
        style={{
          width: "100%",
          fontFamily: "ui-monospace, monospace",
          fontSize: 12,
          lineHeight: 1.5,
          padding: 10,
          borderRadius: 6,
          border: "1px solid #cbd5e1",
          resize: "vertical",
        }}
      />
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}
      >
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={busy !== null || !dirty}
        >
          {busy === "save" ? "Saving…" : "Save override"}
        </button>
        <button
          type="button"
          onClick={() => void onReset()}
          disabled={busy !== null || !prompt.is_overridden}
          title={prompt.is_overridden ? undefined : "No override to reset"}
        >
          {busy === "reset" ? "Resetting…" : "Reset to default"}
        </button>
        {dirty && <small style={{ color: "#b45309" }}>unsaved changes</small>}
        {msg && <small style={{ color: "#15803d" }}>{msg}</small>}
      </div>
    </section>
  );
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPrompts()
      .then(setPrompts)
      .catch((e) => setError(String(e)));
  }, []);

  function update(next: Prompt) {
    setPrompts((ps) => ps?.map((p) => (p.key === next.key ? next : p)) ?? ps);
  }

  return (
    <main
      style={{ maxWidth: 900, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <p style={{ marginBottom: 4 }}>
        <Link href="/">← Studio</Link>
      </p>
      <h1 style={{ marginBottom: 4 }}>Prompts</h1>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          Edit any LLM / Deep Research prompt. Overrides are saved server-side
          and used on the next call across all themes; reset reverts to the
          built-in default. Dynamic context (theme, companies, target count…) is
          added by the engine around this text.
        </small>
      </p>

      {error && (
        <p style={{ color: "crimson" }}>Couldn’t load prompts: {error}</p>
      )}
      {!prompts && !error && <p>Loading…</p>}
      {prompts && (
        <>
          <p style={{ color: "#64748b" }}>
            <small>
              {prompts.length} prompts ·{" "}
              {prompts.filter((p) => p.is_overridden).length} overridden
            </small>
          </p>
          {prompts.map((p) => (
            <PromptCard key={p.key} prompt={p} onChange={update} />
          ))}
        </>
      )}
    </main>
  );
}
