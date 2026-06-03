"use client";

// [M6-FEED-04] Right-panel Live Context Feed: a newest-first stream of raw news /
// interviews / filings, entity-linked to nodes. Selecting a node filters the feed to
// that company; each item links to its source. Context ONLY — no score, momentum, or
// forecast is shown (CLAUDE.md scope).

import { useEffect, useState } from "react";

import { useSelection } from "../canvas/controls";
import { getFeed } from "./api";
import type { FeedItem } from "./types";

const TYPE_COLOR: Record<string, string> = {
  news: "#5ea0ff",
  interview: "#c98a00",
  filing: "#6ee7a8",
};

function timeAgo(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  return new Date(then).toISOString().slice(0, 10);
}

export function FeedPanel({ themeId }: { themeId: string }) {
  const selected = useSelection((s) => s.selected);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [note, setNote] = useState("Loading…");

  useEffect(() => {
    let live = true;
    getFeed(themeId, selected ?? undefined)
      .then((rows) => {
        if (!live) return;
        setItems(rows);
        setNote(rows.length === 0 ? "No context items yet." : "");
      })
      .catch((e) => live && setNote(`Feed unavailable: ${String(e)}`));
    return () => {
      live = false;
    };
  }, [themeId, selected]);

  return (
    <aside
      style={{
        position: "absolute",
        top: 56,
        right: 12,
        bottom: 12,
        width: 320,
        zIndex: 15,
        overflowY: "auto",
        background: "#0e1420f2",
        border: "1px solid #1f2a3d",
        borderRadius: 10,
        padding: 14,
        color: "#cdd6e4",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong style={{ fontSize: 13 }}>Live context</strong>
        <small style={{ opacity: 0.5 }}>raw · no forecasts</small>
      </div>
      {selected && (
        <div style={{ marginTop: 4, opacity: 0.75 }}>
          filtered to {selected}
        </div>
      )}

      {note && <p style={{ opacity: 0.6, marginTop: 12 }}>{note}</p>}

      <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0 }}>
        {items.map((item) => (
          <li
            key={item.id}
            style={{
              padding: "8px 0",
              borderTop: "1px solid #1a2336",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                opacity: 0.7,
              }}
            >
              <span
                style={{
                  color: TYPE_COLOR[item.source_type] ?? "#8a93a8",
                  fontWeight: 600,
                }}
              >
                {item.source_type}
              </span>
              {item.publisher && <span>· {item.publisher}</span>}
              <span style={{ marginLeft: "auto" }}>
                {timeAgo(item.published_at)}
              </span>
            </div>
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              style={{
                color: "#dfe9ff",
                textDecoration: "none",
                fontWeight: 600,
                display: "block",
                margin: "2px 0",
              }}
            >
              {item.title}
            </a>
            {item.snippet && <div style={{ opacity: 0.7 }}>{item.snippet}</div>}
            {item.entities.length > 0 && (
              <div style={{ opacity: 0.5, marginTop: 2 }}>
                {item.entities.join(" · ")}
              </div>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}
