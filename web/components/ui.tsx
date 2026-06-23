"use client";

// ── ValueGraph design-system primitives ────────────────────────────────────
// Single source of truth for the recurring UI patterns from the wireframes
// (see docs/deprecate/DESIGN_SYSTEM.md — design docs being rewritten). Every screen composes these instead of re-deriving
// markup/classes, so the visual language stays unified. Tokens live in globals.css
// :root; these primitives own the structural classNames that consume them.

import { ButtonHTMLAttributes, ReactNode } from "react";

// ── Button ──────────────────────────────────────────────────────────────────
// primary = ink fill · ghost = hairline · danger = light red outline.
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
  size?: "md" | "sm";
};
export function Button({ variant = "primary", size = "md", className = "", ...rest }: ButtonProps) {
  const cls = ["btn",
    variant === "ghost" ? "ghost" : variant === "danger" ? "danger" : "",
    size === "sm" ? "sm" : "", className].filter(Boolean).join(" ");
  return <button className={cls} {...rest} />;
}

// ── Chip / Pill ───────────────────────────────────────────────────────────--
// default = hairline · accent = @group indigo · ink = filled. Optional freshness dot.
export function Chip(
  { tone = "default", dot, onClick, title, children }:
  { tone?: "default" | "accent" | "ink"; dot?: string; onClick?: () => void; title?: string; children: ReactNode },
) {
  const cls = ["chip-ui", tone !== "default" ? `chip-${tone}` : "", onClick ? "chip-btn" : ""].filter(Boolean).join(" ");
  return (
    <span className={cls} onClick={onClick} title={title} role={onClick ? "button" : undefined}>
      {dot ? <FreshnessDot f={dot} /> : null}{children}
    </span>
  );
}

// ── Surface card ──────────────────────────────────────────────────────────--
// White elevated surface with an optional hairline-separated header / footer.
export function Card(
  { head, foot, children, className = "", elevated = true }:
  { head?: ReactNode; foot?: ReactNode; children?: ReactNode; className?: string; elevated?: boolean },
) {
  return (
    <div className={`card-ui ${elevated ? "elevated" : ""} ${className}`.trim()}>
      {head != null ? <div className="card-ui-head">{head}</div> : null}
      {children != null ? <div className="card-ui-body">{children}</div> : null}
      {foot != null ? <div className="card-ui-foot">{foot}</div> : null}
    </div>
  );
}

// ── Trust signals ───────────────────────────────────────────────────────────
// Freshness is computed (fresh <30d · aging <90d · stale). The ONLY saturated color.
export const FRESH_LABEL: Record<string, string> = {
  fresh: "최신 (30일 이내)",
  aging: "갱신 권장",
  stale: "오래됨",
  gap: "공백",
};
export function FreshnessDot({ f }: { f?: string }) {
  if (!f) return null;
  const label = FRESH_LABEL[f] || f;
  return <span className={`fdot ${f}`} title={label} aria-label={label} />;
}
// One legend, reused everywhere a freshness dot appears (the signature legend).
export function TrustLegend() {
  return (
    <div className="legend" aria-label="신선도 범례">
      <span><i className="fdot fresh" /> 최신</span>
      <span><i className="fdot aging" /> 갱신 권장</span>
      <span><i className="fdot stale" /> 오래됨</span>
    </div>
  );
}

// ── Guardrail label ──────────────────────────────────────────────────────────
// The trust brand, shown not hidden (invariant #5). Amber callout.
export function GuardrailLabel({ icon = "🛡", children }: { icon?: string; children: ReactNode }) {
  return <div className="guard">{icon} {children}</div>;
}

// ── Pixel mascot ──────────────────────────────────────────────────────────--
export function Mascot({ size }: { size?: number }) {
  return <span className="mascot" aria-hidden style={size ? { width: size, height: size } : undefined} />;
}

// ── Modal shell ───────────────────────────────────────────────────────────--
// Backdrop + centered panel + head with close. Click-outside / esc closes.
export function Modal(
  { title, onClose, wide, children, footer }:
  { title: ReactNode; onClose: () => void; wide?: boolean; children: ReactNode; footer?: ReactNode },
) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="x" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        {children}
        {footer != null ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}
