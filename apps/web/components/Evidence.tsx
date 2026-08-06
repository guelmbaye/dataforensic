"use client";

import { useMemo, useState } from "react";

import { assetName, clockTime, humanise } from "@/lib/format";
import type { Evidence, Hypothesis } from "@/lib/types";
import { Pill } from "./Primitives";

/**
 * Evidence outranks prose here on purpose: the rail thickness encodes relevance
 * (high signals read as heavier before a single word is), and every item states
 * which system observed it. A judge should be able to see *why* the agent
 * believes it is right without reading a paragraph.
 */
export function EvidenceItem({
  item,
  cited,
}: {
  item: Evidence;
  cited: boolean;
}) {
  return (
    <article className={`evidence ${item.type} ${item.relevance}${cited ? " supporting" : ""}`}>
      <div className="evidence-rail" />
      <div className="evidence-main">
        <div className="evidence-head">
          <span className="evidence-type">{item.type.replace(/_/g, " ")}</span>
          <Pill
            label={item.relevance}
            tone={
              item.relevance === "HIGH"
                ? "accent"
                : item.relevance === "MEDIUM"
                  ? "idle"
                  : "idle"
            }
          />
          {item.observed_at ? (
            <span className="mono small muted">{clockTime(item.observed_at)}</span>
          ) : null}
        </div>

        <p className="evidence-observation" style={{ margin: 0 }}>
          {item.observation}
        </p>

        <div className="evidence-foot">
          <span>observed by {item.source_system.replace(/_/g, " ").toLowerCase()}</span>
          {item.asset_urn ? <span>{assetName(item.asset_urn)}</span> : null}
          {item.lineage_distance !== null ? (
            <span>
              {item.lineage_distance === 0
                ? "on the affected asset"
                : `${item.lineage_distance} hop${item.lineage_distance > 1 ? "s" : ""} upstream`}
            </span>
          ) : null}
          {cited ? <span className="cited">cited by the root cause</span> : null}
        </div>
      </div>
    </article>
  );
}

export function EvidencePanel({
  evidence,
  citedIds,
}: {
  evidence: Evidence[];
  citedIds: string[];
}) {
  const [filter, setFilter] = useState<"all" | "cited" | "high">("all");
  const cited = useMemo(() => new Set(citedIds), [citedIds]);

  const shown = evidence.filter((item) => {
    if (filter === "cited") return cited.has(item.id);
    if (filter === "high") return item.relevance === "HIGH";
    return true;
  });

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Evidence</div>
          <h2 style={{ fontSize: 15 }}>{evidence.length} signals collected</h2>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(
            [
              ["all", "All"],
              ["cited", "Cited"],
              ["high", "High relevance"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`btn ghost small${filter === key ? " accent" : ""}`}
              style={
                filter === key
                  ? { background: "var(--accent)", borderColor: "var(--accent)", color: "#fff" }
                  : undefined
              }
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="panel-body tight">
        {shown.length === 0 ? (
          <p className="small muted" style={{ padding: 16, margin: 0 }}>
            No signal matches this filter.
          </p>
        ) : (
          shown.map((item) => (
            <EvidenceItem key={item.id} item={item} cited={cited.has(item.id)} />
          ))
        )}
      </div>
    </div>
  );
}

export function HypothesisPanel({ hypotheses }: { hypotheses: Hypothesis[] }) {
  if (!hypotheses.length) return null;

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Hypotheses</div>
          <h2 style={{ fontSize: 15 }}>{hypotheses.length} candidates evaluated</h2>
        </div>
        <span className="small muted">Alternatives are scored, not skipped</span>
      </div>

      <div className="panel-body tight">
        {hypotheses.map((hypothesis) => (
          <div
            className={`hyp${hypothesis.is_primary ? " primary" : ""}`}
            key={hypothesis.id}
          >
            <div className="hyp-head">
              <span className="hyp-pattern">{hypothesis.pattern.replace(/_/g, " ")}</span>
              <Pill label={hypothesis.status} />
              {hypothesis.proposed_by !== "engine" ? (
                <span className="mono small muted">via {hypothesis.proposed_by}</span>
              ) : null}
              <span className="hyp-score">{Math.round(hypothesis.confidence * 100)}%</span>
            </div>

            <div className="hyp-meter">
              <span style={{ width: `${Math.max(hypothesis.confidence * 100, 1)}%` }} />
            </div>

            <p className="hyp-reasoning">
              {hypothesis.reasoning_summary || hypothesis.description}
            </p>

            <div className="hyp-counts">
              <span>{hypothesis.supporting_evidence_ids.length} supporting</span>
              <span>{hypothesis.contradicting_evidence_ids.length} contradicting</span>
              <span>{humanise(hypothesis.status)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
