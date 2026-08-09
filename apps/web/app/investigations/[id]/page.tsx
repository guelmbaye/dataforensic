"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { EvidencePanel, HypothesisPanel } from "@/components/Evidence";
import {
  BlastRadiusPanel,
  MemoryPanel,
  RemediationPanel,
  VerificationPanel,
} from "@/components/Impact";
import { InvestigationTimeline } from "@/components/InvestigationTimeline";
import {
  AssetLabel,
  ContextSourceBadge,
  Empty,
  ErrorState,
  Pill,
  Skeleton,
} from "@/components/Primitives";
import { CausalChain, RootCauseCard } from "@/components/RootCause";
import { KnownPatternBanner, LearningFooter, TrustScorePanel } from "@/components/Trust";
import { ApiError, api } from "@/lib/api";
import { useInvestigationStream } from "@/lib/events";
import { assetName, verdictClass } from "@/lib/format";
import type { BlastRadius, Investigation, TrustScore } from "@/lib/types";

type Tab = "investigation" | "impact" | "resolution";

export default function InvestigationPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const investigationId = params?.id ?? null;

  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<Tab>("investigation");
  const [executing, setExecuting] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const evidenceRef = useRef<HTMLDivElement>(null);

  const running = investigation?.status === "RUNNING" || investigation === null;
  const { events, finished } = useInvestigationStream(investigationId, true);

  const refresh = useCallback(() => {
    if (!investigationId) return;
    setError(null);
    api
      .getInvestigation(investigationId)
      .then(setInvestigation)
      .catch((err: ApiError) => setError(err));
  }, [investigationId]);

  useEffect(refresh, [refresh]);

  // The stream tells us when the agent moved on; the projection is fetched
  // again so the panels always show server truth rather than a client guess.
  useEffect(() => {
    if (events.length === 0) return;
    refresh();
  }, [events.length, finished, refresh]);

  // Safety net. SSE can be cut by a proxy, a sleeping tab or a flaky network,
  // and a view that only updates on events would then stay frozen on a running
  // investigation forever. Polling stops as soon as the run is over.
  useEffect(() => {
    if (!investigation || investigation.status !== "RUNNING") return;
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [investigation, refresh]);

  const execute = async (approved: boolean) => {
    if (!investigation?.remediation) return;
    setExecuting(true);
    try {
      await api.executeAction(investigation.remediation.action_id, approved);
      refresh();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setExecuting(false);
    }
  };

  /**
   * A run can end blocked, fail on a transient outage, or be left marked
   * running by an API restart. Without a way back, the incident is stuck and
   * the only recourse is the database.
   */
  const rerun = async () => {
    if (!investigation) return;
    setRerunning(true);
    try {
      const started = await api.investigate(investigation.incident_id, true);
      router.push(`/investigations/${started.investigation_id}`);
    } catch (err) {
      setError(err as ApiError);
      setRerunning(false);
    }
  };

  const showEvidence = () => {
    setTab("investigation");
    requestAnimationFrame(() =>
      evidenceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };

  if (error && !investigation) {
    return (
      <main className="shell page">
        <ErrorState
          title="Cannot load this investigation"
          message={error.message}
          code={error.code}
          onRetry={refresh}
        />
        <p style={{ marginTop: 16 }}>
          <Link href="/">Back to incidents</Link>
        </p>
      </main>
    );
  }

  const blast = investigation?.blast_radius as BlastRadius | undefined;
  const trust =
    investigation && "score" in (investigation.trust ?? {})
      ? (investigation.trust as TrustScore)
      : null;
  const hasBlast = Boolean(blast && blast.total_affected_assets !== undefined);

  return (
    <main className="shell page">
      <div className="page-head">
        <div>
          <div className="eyebrow">
            <Link href="/">Incidents</Link> / investigation
          </div>
          <h1>
            {investigation ? (
              <AssetLabel
                name={assetName(
                  (investigation.context?.asset_urn as string) ?? investigation.incident_id,
                )}
              />
            ) : (
              "Loading"
            )}
          </h1>
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            {investigation ? (
              <>
                <Pill
                  label={investigation.status}
                  tone={verdictClass(investigation.status)}
                  running={investigation.status === "RUNNING"}
                />
                <Pill label={investigation.phase} tone="idle" />
                <ContextSourceBadge mode={investigation.datahub_source_mode} onLight />
              </>
            ) : (
              <Skeleton height={24} width="240px" />
            )}
          </div>
        </div>

        {investigation && investigation.status !== "RUNNING" ? (
          <button type="button" className="btn ghost" onClick={rerun} disabled={rerunning}>
            {rerunning ? "Starting…" : "Re-run investigation"}
          </button>
        ) : null}
      </div>

      <div className="workspace">
        <InvestigationTimeline
          events={events}
          running={running}
          phase={investigation?.phase ?? null}
        />

        <div>
          <div className="tabs" role="tablist">
            <button
              type="button"
              role="tab"
              className="tab"
              aria-selected={tab === "investigation"}
              onClick={() => setTab("investigation")}
            >
              Investigation
              <span className="count">{investigation?.evidence.length ?? 0}</span>
            </button>
            <button
              type="button"
              role="tab"
              className="tab"
              aria-selected={tab === "impact"}
              onClick={() => setTab("impact")}
            >
              Impact
              {hasBlast ? (
                <span className="count">{blast?.total_affected_assets}</span>
              ) : null}
            </button>
            <button
              type="button"
              role="tab"
              className="tab"
              aria-selected={tab === "resolution"}
              onClick={() => setTab("resolution")}
            >
              Resolution &amp; memory
            </button>
          </div>

          {!investigation ? (
            <div className="panel">
              <div className="panel-body" style={{ display: "grid", gap: 12 }}>
                <Skeleton height={120} />
                <Skeleton height={80} />
              </div>
            </div>
          ) : null}

          {investigation && tab === "investigation" ? (
            <>
              <KnownPatternBanner events={events} />

              <RootCauseCard investigation={investigation} onShowEvidence={showEvidence} />

              {trust ? (
                <div style={{ marginTop: 16 }}>
                  <TrustScorePanel trust={trust} />
                </div>
              ) : null}

              {investigation.causal_chain.length ? (
                <div className="panel" style={{ marginTop: 16 }}>
                  <div className="panel-head">
                    <div className="eyebrow">Causal chain</div>
                    <span className="small muted">each step carries its evidence</span>
                  </div>
                  <div className="panel-body tight">
                    <CausalChain steps={investigation.causal_chain} />
                  </div>
                </div>
              ) : null}

              <div ref={evidenceRef} style={{ marginTop: 16 }}>
                <EvidencePanel
                  evidence={investigation.evidence}
                  citedIds={investigation.root_cause.evidence_ids}
                />
              </div>

              <div style={{ marginTop: 16 }}>
                <HypothesisPanel hypotheses={investigation.hypotheses} />
              </div>
            </>
          ) : null}

          {investigation && tab === "impact" ? (
            hasBlast && blast ? (
              <BlastRadiusPanel blast={blast} />
            ) : (
              <div className="panel">
                <div className="panel-body">
                  <Empty
                    title="Impact not calculated yet"
                    message="The blast radius is walked once a root cause is established, starting from where the defect enters the graph."
                  />
                </div>
              </div>
            )
          ) : null}

          {investigation && tab === "resolution" ? (
            <>
              {investigation.remediation ? (
                <RemediationPanel
                  remediation={investigation.remediation}
                  onExecute={execute}
                  executing={executing}
                />
              ) : (
                <div className="panel">
                  <div className="panel-body">
                    <Empty
                      title="No plan yet"
                      message="A remediation plan is written once the agent can name a cause worth fixing."
                    />
                  </div>
                </div>
              )}

              {investigation.verification ? (
                <div style={{ marginTop: 16 }}>
                  <VerificationPanel verification={investigation.verification} />
                </div>
              ) : null}

              <div style={{ marginTop: 16 }}>
                <MemoryPanel memory={investigation.memory} />
              </div>

              <div style={{ marginTop: 16 }}>
                <LearningFooter learning={investigation.learning} />
              </div>
            </>
          ) : null}

          {investigation?.reasoning_engine ? (
            <p className="small muted mono" style={{ marginTop: 20 }}>
              reasoning engine: {investigation.reasoning_engine}
            </p>
          ) : null}
        </div>
      </div>
    </main>
  );
}
