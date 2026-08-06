"use client";

import { humanise } from "@/lib/format";
import type { Investigation, ScoreBreakdown } from "@/lib/types";

const SEGMENTS = [
  { key: "evidence_strength", label: "Evidence strength", cls: "evidence", max: 30 },
  { key: "lineage_relevance", label: "Lineage relevance", cls: "lineage", max: 25 },
  { key: "temporal_correlation", label: "Temporal correlation", cls: "temporal", max: 20 },
  { key: "cross_signal_agreement", label: "Cross-signal agreement", cls: "cross", max: 25 },
] as const;

/**
 * The score that shows its work.
 *
 * A confidence number on its own is an assertion. Broken into the four things
 * that produced it — and the contradictions that were subtracted — it becomes
 * something a reader can argue with, which is the point.
 */
export function ScoreBreakdownBar({ breakdown }: { breakdown: ScoreBreakdown }) {
  const penalty = Math.abs(breakdown.contradicting_evidence ?? 0);
  const positive = SEGMENTS.reduce(
    (sum, segment) => sum + (breakdown[segment.key] ?? 0),
    0,
  );
  const span = Math.max(positive + penalty, 100);

  return (
    <div className="score">
      <div className="eyebrow" style={{ marginBottom: 8 }}>
        How this confidence was calculated
      </div>

      <div
        className="score-bar"
        role="img"
        aria-label={`Confidence ${Math.round(breakdown.total ?? 0)} out of 100`}
      >
        {SEGMENTS.map((segment) => {
          const value = breakdown[segment.key] ?? 0;
          if (value <= 0) return null;
          return (
            <div
              key={segment.key}
              className={`score-seg ${segment.cls}`}
              style={{ width: `${(value / span) * 100}%` }}
              title={`${segment.label}: ${value} of ${segment.max}`}
            />
          );
        })}
        {penalty > 0 ? (
          <div
            className="score-seg penalty"
            style={{ width: `${(penalty / span) * 100}%` }}
            title={`Contradicting evidence: −${penalty}`}
          />
        ) : null}
      </div>

      <ul className="score-legend">
        {SEGMENTS.map((segment) => (
          <li key={segment.key}>
            <span className={`swatch score-seg ${segment.cls}`} />
            {segment.label} <b>{breakdown[segment.key] ?? 0}</b>
            <span className="muted">/{segment.max}</span>
          </li>
        ))}
        <li>
          <span className="swatch score-seg penalty" />
          Contradicting evidence <b>−{penalty}</b>
        </li>
      </ul>

      <p className="score-formula">
        evidence + lineage + temporal + cross-signal − contradictions ={" "}
        <b>{Math.round(breakdown.total ?? 0)}</b> / 100
      </p>
    </div>
  );
}

export function RootCauseCard({
  investigation,
  onShowEvidence,
}: {
  investigation: Investigation;
  onShowEvidence: () => void;
}) {
  const { root_cause: cause } = investigation;

  if (investigation.status === "BLOCKED") {
    return (
      <div className="blocked">
        <div className="eyebrow">Investigation blocked</div>
        <h2 style={{ margin: "6px 0 8px" }}>No root cause was published</h2>
        <p style={{ margin: 0 }}>
          {investigation.blocked_reason ??
            "The agent could not gather enough context to support a conclusion."}
        </p>
        <p className="small muted" style={{ margin: "10px 0 0" }}>
          The agent stops rather than name a cause it cannot evidence. Restore the
          context source and run the investigation again.
        </p>
      </div>
    );
  }

  if (investigation.status === "FAILED") {
    return (
      <div className="error-state">
        <h3>The investigation stopped early</h3>
        <p style={{ margin: "0 0 8px" }}>{investigation.error ?? "Unexpected failure."}</p>
        <p className="small" style={{ margin: 0 }}>
          Nothing was concluded and nothing was written back.
        </p>
      </div>
    );
  }

  if (!cause.pattern) {
    return (
      <div className="panel">
        <div className="panel-body">
          <div className="eyebrow">Root cause</div>
          <p className="muted" style={{ margin: "8px 0 0" }}>
            Still gathering evidence. A cause appears here once a hypothesis is
            supported by more than the reported symptom.
          </p>
        </div>
      </div>
    );
  }

  return (
    <section className="rootcause">
      <header className="rootcause-head">
        <div>
          <div className="eyebrow">Probable root cause</div>
          <div className="rootcause-pattern">{cause.pattern.replace(/_/g, " ")}</div>
        </div>
        <div className="confidence">
          <b>{Math.round(cause.confidence * 100)}%</b>
          <div className="eyebrow" style={{ marginTop: 4 }}>
            confidence
          </div>
        </div>
      </header>

      <div className="rootcause-body">
        <p className="rootcause-summary">{cause.summary}</p>

        {cause.reasoning ? (
          <p className="small muted" style={{ margin: "0 0 16px" }}>
            {cause.reasoning}
          </p>
        ) : null}

        <button type="button" className="btn ghost small" onClick={onShowEvidence}>
          Show the {cause.evidence_ids.length} supporting signals
        </button>

        <ScoreBreakdownBar breakdown={cause.score_breakdown} />
      </div>
    </section>
  );
}

export function CausalChain({ steps }: { steps: Investigation["causal_chain"] }) {
  if (!steps.length) return null;
  return (
    <div className="chain">
      {steps.map((step) => (
        <div className="chain-step" key={step.step}>
          <div className="chain-index">{step.step}</div>
          <div>
            <div className="chain-label">{step.label}</div>
            <div className="chain-detail">{step.detail}</div>
            {step.asset_name ? (
              <div className="small muted mono" style={{ marginTop: 4 }}>
                {step.asset_name} · {humanise(step.evidence_type)}
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
