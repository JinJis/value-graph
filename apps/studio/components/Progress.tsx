"use client";

import { useEffect, useRef } from "react";

import { Markdown } from "./Markdown";

// Live view of a streamed LLM run (fed by the SSE stream). Shows, top to bottom: which
// Gemini model is routed and where the call goes, the step timeline, the exact prompt
// sent, and the model's output as it streams in. Pass `markdown` to render the output as
// Markdown (e.g. a Deep Research report) instead of raw monospace text.

export interface ProgStep {
  label: string;
  detail?: string;
  tone?: "ok" | "warn" | "err";
}

export interface Prog {
  model?: { tier: string; model: string };
  endpoint?: { provider: string; method: string };
  prompt?: string;
  output: string;
  steps: ProgStep[];
  error?: string;
  done: boolean;
  running: boolean;
}

const TONE: Record<string, string> = {
  ok: "#15803d",
  warn: "#b45309",
  err: "#b91c1c",
};

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 6,
        background: "#0f172a",
        color: "#e2e8f0",
        fontSize: 12,
        fontFamily: "ui-monospace, monospace",
      }}
    >
      {children}
    </span>
  );
}

export function BlueprintProgress({
  prog,
  markdown = false,
}: {
  prog: Prog;
  markdown?: boolean;
}) {
  const outRef = useRef<HTMLDivElement>(null);

  // Keep the streaming output scrolled to the newest tokens.
  useEffect(() => {
    if (outRef.current) outRef.current.scrollTop = outRef.current.scrollHeight;
  }, [prog.output]);

  const hasAny =
    prog.running ||
    prog.done ||
    prog.error ||
    prog.steps.length > 0 ||
    !!prog.model;
  if (!hasAny) return null;

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
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <strong style={{ fontSize: 14 }}>
          {prog.running ? "Generating…" : prog.done ? "Done" : "Generation"}
        </strong>
        {prog.model && (
          <Badge>
            {prog.model.tier} · {prog.model.model}
          </Badge>
        )}
        {prog.endpoint && (
          <Badge>
            {prog.endpoint.provider}.{prog.endpoint.method}
          </Badge>
        )}
        {prog.running && (
          <span style={{ fontSize: 12, color: "#64748b" }}>
            streaming {prog.output.length.toLocaleString()} chars…
          </span>
        )}
      </div>

      {prog.error && (
        <p style={{ color: TONE.err, marginTop: 8, fontSize: 13 }}>
          ✗ {prog.error}
        </p>
      )}

      {prog.steps.length > 0 && (
        <ol style={{ margin: "8px 0", paddingLeft: 18, fontSize: 13 }}>
          {prog.steps.map((s, i) => (
            <li key={i} style={{ color: s.tone ? TONE[s.tone] : "#334155" }}>
              {s.label}
              {s.detail && (
                <span style={{ color: "#64748b" }}> — {s.detail}</span>
              )}
            </li>
          ))}
        </ol>
      )}

      {prog.prompt && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: "pointer", fontSize: 13 }}>
            Prompt sent ({prog.prompt.length.toLocaleString()} chars)
          </summary>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: 12,
              background: "#0f172a",
              color: "#e2e8f0",
              padding: 12,
              borderRadius: 6,
              maxHeight: 280,
              overflow: "auto",
            }}
          >
            {prog.prompt}
          </pre>
        </details>
      )}

      {prog.output && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 13, marginBottom: 4 }}>
            {markdown ? "Research report" : "Model output"}
          </div>
          <div
            ref={outRef}
            style={{
              maxHeight: 320,
              overflow: "auto",
              borderRadius: 6,
              padding: 12,
              ...(markdown
                ? {
                    background: "#ffffff",
                    border: "1px solid #e2e8f0",
                    color: "#0f172a",
                  }
                : { background: "#0b1020" }),
            }}
          >
            {markdown ? (
              <Markdown source={prog.output} />
            ) : (
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  fontSize: 12,
                  color: "#7dd3fc",
                  margin: 0,
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                {prog.output}
              </pre>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
