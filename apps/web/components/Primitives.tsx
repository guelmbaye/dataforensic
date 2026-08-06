"use client";

import { verdictClass } from "@/lib/format";
import type { SourceMode } from "@/lib/types";

export function Pill({
  label,
  tone,
  running = false,
}: {
  label: string;
  tone?: string;
  running?: boolean;
}) {
  const cls = tone ?? verdictClass(label);
  return (
    <span className={`pill ${cls}${running ? " running" : ""}`}>
      <span className="dot" />
      {label.replace(/_/g, " ")}
    </span>
  );
}

/**
 * The single most important label on screen: whether the context the agent
 * reasoned over came from a live DataHub or from the deterministic fallback.
 * It is never inferred or defaulted — it renders exactly what the API reports.
 */
export function ContextSourceBadge({
  mode,
  detail,
  onLight = false,
}: {
  mode: SourceMode | string | null | undefined;
  detail?: string;
  /** The header of an investigation sits on the light canvas, not the ink bar. */
  onLight?: boolean;
}) {
  const surface = onLight ? " on-light" : "";
  if (mode === "LIVE_DATAHUB") {
    return (
      <span className={`source-badge live${surface}`} title={detail ?? "Connected to DataHub"}>
        <span className="source-dot" />
        Live DataHub
      </span>
    );
  }
  if (mode === "DEMO_FIXTURE") {
    return (
      <span
        className={`source-badge fixture${surface}`}
        title={detail ?? "Deterministic context graph — no live DataHub was queried"}
      >
        <span className="source-dot" />
        Demo context graph
      </span>
    );
  }
  return (
    <span className={`source-badge unknown${surface}`} title={detail ?? "Context source unknown"}>
      <span className="source-dot" />
      Context source unknown
    </span>
  );
}

/**
 * A qualified asset name with break opportunities at its separators.
 *
 * `ECOMMERCE.ANALYTICS.SALES_DAILY` is one unbreakable word to the layout
 * engine. Letting CSS break it anywhere stops the page overflowing but splits
 * it mid-token; `<wbr>` after each separator breaks where a reader already
 * sees a boundary, and — unlike a zero-width space — it never ends up in the
 * clipboard when someone copies the name.
 */
export function AssetLabel({ name }: { name: string }) {
  const parts = name.split(/(?<=[._\-/])/);
  return (
    <>
      {parts.map((part, index) => (
        <span key={`${part}-${index}`}>
          {part}
          {index < parts.length - 1 ? <wbr /> : null}
        </span>
      ))}
    </>
  );
}

export function ErrorState({
  title,
  message,
  code,
  onRetry,
}: {
  title: string;
  message: string;
  code?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-state">
      <h3>{title}</h3>
      <p style={{ margin: "0 0 10px" }}>{message}</p>
      {code ? (
        <p style={{ margin: "0 0 12px" }}>
          <code>{code}</code>
        </p>
      ) : null}
      {onRetry ? (
        <button type="button" className="btn ghost small" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Empty({
  title,
  message,
  children,
}: {
  title: string;
  message: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p style={{ margin: "0 0 14px" }}>{message}</p>
      {children}
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: string }) {
  return <div className="skeleton" style={{ height, width }} />;
}

export function PanelHead({
  eyebrow,
  title,
  right,
}: {
  eyebrow?: string;
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="panel-head">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h2 style={{ fontSize: 15 }}>{title}</h2>
      </div>
      {right}
    </div>
  );
}
