"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Empty, ErrorState, Pill, Skeleton } from "@/components/Primitives";
import { PatternHistory } from "@/components/Trust";
import { ApiError, api } from "@/lib/api";
import { assetName, dateTime, percent } from "@/lib/format";
import type { KnowledgePattern } from "@/lib/types";

export default function PatternsPage() {
  const [patterns, setPatterns] = useState<KnowledgePattern[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .listPatterns()
      .then((page) => setPatterns(page.items))
      .catch((err: ApiError) => setError(err));
  }, []);

  useEffect(load, [load]);

  const totalIncidents = (patterns ?? []).reduce((sum, p) => sum + p.occurrences, 0);
  const totalVerified = (patterns ?? []).reduce((sum, p) => sum + p.verified_resolutions, 0);

  return (
    <main className="shell page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Organisational memory</div>
          <h1>What this DataHub has learned</h1>
          <p>
            Each entry is a failure mode the organisation has actually lived through:
            the symptoms it shows up as, the signals that prove it, and the
            remediation that was verified. Patterns are built from resolved
            investigations only — nothing here was written by hand.
          </p>
        </div>
        <Link href="/" className="btn ghost">
          Back to incidents
        </Link>
      </div>

      {error ? (
        <ErrorState
          title="Cannot load the pattern library"
          message={error.message}
          code={error.code}
          onRetry={load}
        />
      ) : null}

      {patterns === null && !error ? (
        <div className="panel">
          <div className="panel-body" style={{ display: "grid", gap: 12 }}>
            <Skeleton height={72} />
            <Skeleton height={72} />
          </div>
        </div>
      ) : null}

      {patterns?.length === 0 ? (
        <div className="panel">
          <div className="panel-body">
            <Empty
              title="Nothing learned yet"
              message={
                "Resolve an incident and its pattern appears here. If incidents " +
                "are already resolved and this stays empty, open one and check " +
                "its Resolution & memory tab — the write-back reports what went wrong."
              }
            >
              <Link href="/" className="btn">
                Go to incidents
              </Link>
            </Empty>
          </div>
        </div>
      ) : null}

      {patterns && patterns.length > 0 ? (
        <>
          <div className="panel">
            <div className="stat-row" style={{ borderTop: "none" }}>
              <div className="stat">
                <b>{patterns.length}</b>
                <span>failure modes known</span>
              </div>
              <div className="stat">
                <b>{totalIncidents}</b>
                <span>investigations folded in</span>
              </div>
              <div className="stat">
                <b>{totalVerified}</b>
                <span>verified resolutions</span>
              </div>
            </div>
          </div>

          {patterns.map((pattern) => {
            const expanded = open === pattern.pattern;
            return (
              <div className="panel" key={pattern.pattern}>
                <div className="panel-head">
                  <div style={{ minWidth: 0 }}>
                    <div className="eyebrow">Knowledge pattern</div>
                    <h2 className="mono" style={{ fontSize: 17, marginTop: 3 }}>
                      {pattern.pattern.replace(/_/g, " ")}
                    </h2>
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <Pill
                      label={`seen ${pattern.occurrences}x`}
                      tone={pattern.occurrences > 1 ? "accent" : "idle"}
                    />
                    <Pill
                      label={`${pattern.verified_resolutions} verified`}
                      tone={pattern.verified_resolutions ? "pass" : "warn"}
                    />
                  </div>
                </div>

                <div className="panel-body">
                  {pattern.description ? (
                    <p style={{ margin: "0 0 14px", maxWidth: "72ch" }}>
                      {pattern.description}
                    </p>
                  ) : null}

                  <dl className="kv">
                    <dt>Symptoms</dt>
                    <dd>
                      {pattern.symptoms.length
                        ? pattern.symptoms.join(" · ")
                        : "not recorded"}
                    </dd>

                    <dt>Evidence signature</dt>
                    <dd className="mono small">
                      {pattern.evidence_signature.join(" + ") || "not recorded"}
                    </dd>

                    <dt>Verified fix</dt>
                    <dd>
                      {pattern.resolution_steps.length ? (
                        <ol className="recall-steps" style={{ margin: 0 }}>
                          {pattern.resolution_steps.map((step) => (
                            <li key={step}>{step}</li>
                          ))}
                        </ol>
                      ) : (
                        "no verified remediation yet"
                      )}
                    </dd>

                    <dt>Assets touched</dt>
                    <dd className="mono small">
                      {pattern.affected_asset_urns.slice(0, 4).map(assetName).join(", ") ||
                        "—"}
                      {pattern.affected_asset_urns.length > 4
                        ? ` +${pattern.affected_asset_urns.length - 4} more`
                        : ""}
                    </dd>

                    <dt>Average</dt>
                    <dd className="mono small">
                      confidence {percent(pattern.average_confidence)} · trust{" "}
                      {pattern.average_trust_score}/100
                    </dd>

                    <dt>Last seen</dt>
                    <dd className="mono small">{dateTime(pattern.last_seen)}</dd>
                  </dl>

                  <button
                    type="button"
                    className="btn ghost small"
                    style={{ marginTop: 14 }}
                    onClick={() => setOpen(expanded ? null : pattern.pattern)}
                  >
                    {expanded ? "Hide" : "Show"} the {pattern.history.length} investigation
                    {pattern.history.length === 1 ? "" : "s"} behind this pattern
                  </button>
                </div>

                {expanded ? <PatternHistory history={pattern.history} /> : null}
              </div>
            );
          })}
        </>
      ) : null}
    </main>
  );
}
