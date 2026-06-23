"use client";

import { useMemo } from "react";

export type WaterfallPrompt = {
  id: string;
  title: string;
  description?: string | null;
  category?: string | null;
  body: string;
};

// The chat home "waterfall": example questions from the prompt library rise from the bottom
// in a seamless infinite loop, hinting at what the desk can do. Hovering pauses it (so a user
// can read/click). Each chip shows a SHORT summary; clicking drops the FULL prompt into the
// composer (not sent) — the user can then fill {TICKER} and send.
export default function PromptWaterfall({
  prompts,
  onPick,
}: {
  prompts: WaterfallPrompt[];
  onPick: (body: string) => void;
}) {
  const items = useMemo(() => prompts.filter((p) => p.body), [prompts]);
  if (items.length === 0) return null;
  // render the list TWICE so translateY(-50%) lands exactly one copy up → seamless loop.
  const loop = [...items, ...items];
  // constant scroll speed regardless of how many prompts there are.
  const duration = Math.max(20, items.length * 3.4);
  return (
    <div className="pwf" aria-label="예시 질문 — 마우스를 올리면 멈춥니다">
      <div className="pwf-track" style={{ animationDuration: `${duration}s` }}>
        {loop.map((p, i) => {
          const dup = i >= items.length; // the duplicated half is decorative (not focusable)
          return (
            <button
              key={`${p.id}-${i}`}
              type="button"
              className="pwf-chip"
              onClick={() => onPick(p.body)}
              title={p.body}
              aria-hidden={dup}
              tabIndex={dup ? -1 : 0}
            >
              {p.category ? <span className="pwf-cat">{p.category}</span> : null}
              <span className="pwf-text">{p.description || p.title}</span>
              <span className="pwf-arrow" aria-hidden>↳</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
