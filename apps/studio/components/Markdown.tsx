import React from "react";

// Minimal, dependency-free Markdown renderer for the streamed Deep Research report.
// Handles headings, bold/italic, inline code, links, bullet/numbered lists, code fences,
// blockquotes and paragraphs. It is line-based and tolerant of partial/streaming input
// (an unclosed code fence or half-written emphasis just renders gracefully). Underscores
// are intentionally NOT treated as emphasis so identifiers like as_of_date / snake_case
// survive untouched.

const codeInline: React.CSSProperties = {
  background: "#eef2f7",
  borderRadius: 4,
  padding: "0 4px",
  fontFamily: "ui-monospace, monospace",
  fontSize: "0.92em",
};

const codeBlock: React.CSSProperties = {
  background: "#0b1020",
  color: "#7dd3fc",
  borderRadius: 6,
  padding: 10,
  overflow: "auto",
  fontFamily: "ui-monospace, monospace",
  fontSize: 12,
  whiteSpace: "pre-wrap",
  margin: "8px 0",
};

const quoteStyle: React.CSSProperties = {
  borderLeft: "3px solid #cbd5e1",
  margin: "6px 0",
  padding: "2px 0 2px 10px",
  color: "#475569",
};

const H_SIZE: Record<number, number> = {
  1: 20,
  2: 18,
  3: 16,
  4: 14,
  5: 13,
  6: 13,
};

// Inline emphasis/code/link tokenizer. Group order: bold, italic, code, link(text,url).
const INLINE_RE =
  /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\))/g;

function inline(text: string, keyBase: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const key = `${keyBase}-${i++}`;
    if (m[2] !== undefined) {
      nodes.push(<strong key={key}>{m[2]}</strong>);
    } else if (m[3] !== undefined) {
      nodes.push(<em key={key}>{m[3]}</em>);
    } else if (m[4] !== undefined) {
      nodes.push(
        <code key={key} style={codeInline}>
          {m[4]}
        </code>,
      );
    } else if (m[5] !== undefined && m[6] !== undefined) {
      nodes.push(
        <a key={key} href={m[6]} target="_blank" rel="noreferrer">
          {m[5]}
        </a>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const blocks: React.ReactNode[] = [];
  let key = 0;
  let i = 0;
  let listItems: React.ReactNode[] | null = null;
  let listOrdered = false;

  const flushList = () => {
    if (!listItems) return;
    const style: React.CSSProperties = { margin: "6px 0", paddingLeft: 20 };
    blocks.push(
      listOrdered ? (
        <ol key={key++} style={style}>
          {listItems}
        </ol>
      ) : (
        <ul key={key++} style={style}>
          {listItems}
        </ul>
      ),
    );
    listItems = null;
  };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block (tolerates a missing closing fence while streaming).
    if (line.trimStart().startsWith("```")) {
      flushList();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // skip the closing fence if present
      blocks.push(
        <pre key={key++} style={codeBlock}>
          {buf.join("\n")}
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushList();
      const level = heading[1].length;
      blocks.push(
        React.createElement(
          `h${level}`,
          {
            key: key++,
            style: { fontSize: H_SIZE[level], margin: "10px 0 4px" },
          },
          inline(heading[2], `h${i}`),
        ),
      );
      i++;
      continue;
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (bullet || ordered) {
      const isOrdered = !!ordered;
      if (listItems && listOrdered !== isOrdered) flushList();
      if (!listItems) {
        listItems = [];
        listOrdered = isOrdered;
      }
      listItems.push(
        <li key={`li-${i}`}>{inline((bullet ?? ordered)![1], `li${i}`)}</li>,
      );
      i++;
      continue;
    }

    if (line.trim() === "") {
      flushList();
      i++;
      continue;
    }

    const quote = /^\s*>\s?(.*)$/.exec(line);
    if (quote) {
      flushList();
      blocks.push(
        <blockquote key={key++} style={quoteStyle}>
          {inline(quote[1], `bq${i}`)}
        </blockquote>,
      );
      i++;
      continue;
    }

    // Paragraph: merge consecutive plain lines until a blank or a block marker.
    flushList();
    const para: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,6})\s|^\s*[-*+]\s|^\s*\d+\.\s|```|^\s*>/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} style={{ margin: "6px 0" }}>
        {inline(para.join(" "), `p${i}`)}
      </p>,
    );
  }
  flushList();

  return <div style={{ fontSize: 13, lineHeight: 1.5 }}>{blocks}</div>;
}
