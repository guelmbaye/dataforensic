"use client";

import { dateTime, percent } from "@/lib/format";
import type { InvestigationEvent, Learning, PatternMatch, TrustScore } from "@/lib/types";

const DECISION_LABEL: Record<string, string> = {
  HIGH_CONFIDENCE: "High confidence",
  MODERATE_CONFIDENCE: "Moderate confidence",
  LOW_CONFIDENCE: "Low confidence",
  INSUFFICIENT_GROUNDING: "Insufficient grounding",
};

function statusTone(status: string): string {
  if (status === "PASS") return "pass";
  if (status === "PARTIAL") return "warn";
  return "fail";
}

/**
 * The second number.
 *
 * Confidence says how strongly the evidence points at this cause. Trust says how
 * much of the investigation was grounded in retrieved context at all. Showing
 * them side by side is the honest answer to "why should I believe an AI here" —
 * and the two are allowed to disagree.
 */
export function TrustScorePanel({ trust }: { trust: TrustScore }) {
  const tone =
    trust.score >= 85 ? "pass" : trust.score >= 65 ? "warn" : "fail";

  return (
    <div className="panel trust">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Investigation trust score</div>
          <h2 style={{ fontSize: 15 }}>How grounded is this conclusion?</h2>
        </div>
        <div className={`trust-figure ${tone}`}>
          <b>{Math.round(trust.score)}</b>
          <span>/ {trust.max_score}</span>
        </div>
      </div>

      <div className="panel-body tight">
        {trust.checks.map((check) => (
          <div className="trust-check" key={check.key}>
            <div className={`trust-mark ${statusTone(check.status)}`}>
              {check.status === "PASS" ? "✓" : check.status === "PARTIAL" ? "~" : "✕"}
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="trust-label">
                {check.label}
                <span className="trust-points">
                  {check.points} / {check.max_points}
                </span>
              </div>
              <div className="trust-meter">
                <span
                  className={statusTone(check.status)}
                  style={{ width: `${(check.points / check.max_points) * 100}%` }}
                />
              </div>
              <p className="trust-detail">{check.detail}</p>
            </div>
          </div>
        ))}
      </div>

      <div className={`verdict ${tone}`}>
        <div>
          <div className="verdict-label">{DECISION_LABEL[trust.decision] ?? trust.decision}</div>
          <div className="small" style={{ marginTop: 2 }}>
            {trust.rationale}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * What the organisation already knew when this incident arrived.
 *
 * Deliberately worded as a lead rather than an answer: the agent still runs the
 * full investigation, and the banner would still be here if the pattern turned
 * out not to fit.
 */
export function KnownPatternBanner({ events }: { events: InvestigationEvent[] }) {
  const detected = events.find((event) => event.event === "known_pattern_detected");
  if (!detected) return null;

  const payload = detected.payload as unknown as PatternMatch & {
    recommended_remediation?: string[];
    match_reasons?: string[];
  };

  return (
    <div className="recall">
      <div className="recall-head">
        <div>
          <div className="eyebrow">Known pattern recognised</div>
          <h2 className="mono" style={{ fontSize: 20, marginTop: 4 }}>
            {payload.pattern?.replace(/_/g, " ")}
          </h2>
        </div>
        <div className="recall-similarity">
          <b>{percent(payload.similarity)}</b>
          <span>similarity</span>
        </div>
      </div>

      <p style={{ margin: "10px 0 12px" }}>
        This organisation has seen this failure mode{" "}
        <b>{payload.occurrences}×</b> before, with{" "}
        <b>{payload.verified_resolutions}</b> verified resolution
        {payload.verified_resolutions === 1 ? "" : "s"}. The agent treated it as a
        lead and still ran the full investigation.
      </p>

      {payload.recommended_remediation?.length ? (
        <>
          <div className="eyebrow">Remediation that worked last time</div>
          <ol className="recall-steps">
            {payload.recommended_remediation.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </>
      ) : null}

      {payload.match_reasons?.length ? (
        <p className="small muted mono" style={{ margin: "10px 0 0" }}>
          matched on: {payload.match_reasons.join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

/** What the memory cost or saved, measured rather than claimed. */
export function LearningFooter({ learning }: { learning: Learning }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="eyebrow">Investigation cost</div>
        <span className="small muted">measured, not estimated</span>
      </div>
      <div className="stat-row">
        <div className="stat">
          <b>{learning.tool_call_count}</b>
          <span>DataHub calls</span>
        </div>
        <div className="stat">
          <b>{(learning.duration_ms / 1000).toFixed(1)}s</b>
          <span>reasoning time</span>
        </div>
        <div className="stat">
          <b>{learning.memory_assisted ? "Yes" : "No"}</b>
          <span>prior knowledge</span>
        </div>
        <div className="stat">
          <b className="mono" style={{ fontSize: 14 }}>
            {learning.remediation_source === "generated" ? "Generated" : "Reused"}
          </b>
          <span>remediation</span>
        </div>
      </div>
      {learning.reused_from_investigation_id ? (
        <div className="panel-body">
          <p className="small muted" style={{ margin: 0 }}>
            The plan applied here is the one verified in investigation{" "}
            <span className="mono">
              {learning.reused_from_investigation_id.slice(0, 8)}
            </span>
            , not a newly generated guess.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function PatternHistory({ history }: { history: Record<string, unknown>[] }) {
  if (!history.length) return null;
  return (
    <div className="panel-body tight">
      {history.map((entry, index) => (
        <div className="check" key={String(entry.investigation_id ?? index)}>
          <div>
            <div className="check-name">
              {String(entry.investigation_id ?? "").slice(0, 8) || "investigation"}
            </div>
            <div className="check-values">
              confidence {percent(Number(entry.confidence ?? 0))} · trust{" "}
              {String(entry.trust_score ?? "—")} · {String(entry.tool_calls ?? 0)} calls ·{" "}
              {dateTime(String(entry.recorded_at ?? ""))}
            </div>
          </div>
          <span className={`pill ${entry.verified ? "pass" : "warn"}`}>
            <span className="dot" />
            {entry.verified ? "verified" : "unverified"}
          </span>
        </div>
      ))}
    </div>
  );
}
