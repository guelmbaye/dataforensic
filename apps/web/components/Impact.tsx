"use client";

import { assetName, dateTime, humanise } from "@/lib/format";
import type {
  BlastRadius,
  MemoryReference,
  Remediation,
  Verification,
} from "@/lib/types";
import { AssetLabel, Empty, Pill } from "./Primitives";

const BUCKET_LABELS: Record<string, string> = {
  datasets: "Datasets",
  dashboards: "Dashboards",
  charts: "Charts",
  ml_assets: "ML assets",
  data_jobs: "Pipelines",
  consumers_other: "Other consumers",
};

export function BlastRadiusPanel({ blast }: { blast: BlastRadius }) {
  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Blast radius</div>
            <h2 style={{ fontSize: 15 }}>
              Downstream of {blast.origin_name ?? assetName(blast.origin_urn)}
            </h2>
          </div>
          <Pill
            label={blast.risk_level}
            tone={
              blast.risk_level === "CRITICAL" || blast.risk_level === "HIGH"
                ? "fail"
                : blast.risk_level === "MEDIUM"
                  ? "warn"
                  : "idle"
            }
          />
        </div>

        <div className="stat-row">
          <div className="stat">
            <b>{blast.total_affected_assets}</b>
            <span>assets affected</span>
          </div>
          <div className="stat">
            <b>{blast.consumers}</b>
            <span>end consumers</span>
          </div>
          <div className="stat">
            <b>{blast.owner_count}</b>
            <span>owning teams</span>
          </div>
          <div className="stat">
            <b>{Math.round(blast.risk_score)}</b>
            <span>risk score</span>
          </div>
        </div>

        <div className="panel-body">
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", marginBottom: 12 }}>
            {Object.entries(blast.counts)
              .filter(([, count]) => count > 0)
              .map(([bucket, count]) => (
                <span key={bucket} className="mono small">
                  <b>{count}</b>{" "}
                  <span className="muted">{BUCKET_LABELS[bucket] ?? humanise(bucket)}</span>
                </span>
              ))}
          </div>

          {blast.risk_factors.length ? (
            <ul style={{ margin: 0, paddingLeft: 18 }} className="small">
              {blast.risk_factors.map((factor) => (
                <li key={factor}>{factor}</li>
              ))}
            </ul>
          ) : null}

          <p className="small muted" style={{ margin: "12px 0 0" }}>
            Counted from {String(blast.computed_from?.lineage_node_count ?? 0)} lineage
            nodes returned by DataHub, not from a fixed list.
          </p>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div className="eyebrow">Affected assets</div>
          <span className="small muted">nearest first</span>
        </div>
        <div className="panel-body tight">
          {blast.affected_assets.map((asset) => (
            <div className="asset" key={asset.urn}>
              <div className="asset-hop">{asset.distance ?? "?"}↓</div>
              <div style={{ minWidth: 0 }}>
                <div className="asset-name">
                  <AssetLabel name={asset.name} />
                </div>
                <div className="asset-kind">
                  {humanise(asset.entity_type)}
                  {asset.platform ? ` · ${asset.platform}` : ""}
                </div>
              </div>
              <div className="asset-meta">
                {asset.criticality === "CRITICAL" || asset.criticality === "HIGH" ? (
                  <span className="tag critical">{asset.criticality}</span>
                ) : null}
                {asset.owners?.[0]?.name ? (
                  <div className="small muted" style={{ marginTop: 4 }}>
                    {asset.owners[0].name}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      {blast.owners.length ? (
        <div className="panel">
          <div className="panel-head">
            <div className="eyebrow">Who needs to know</div>
            <span className="small muted">{blast.owner_count} teams</span>
          </div>
          <div className="panel-body tight">
            {blast.owners.map((owner) => (
              <div className="asset" key={owner.urn ?? owner.name}>
                <div className="asset-hop">{owner.assets?.length ?? 0}</div>
                <div>
                  <div className="asset-name">{owner.name}</div>
                  <div className="asset-kind">{owner.email ?? owner.urn}</div>
                </div>
                <span className="small muted">{humanise(owner.type ?? "")}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

export function RemediationPanel({
  remediation,
  onExecute,
  executing,
}: {
  remediation: Remediation;
  onExecute: (approved: boolean) => void;
  executing: boolean;
}) {
  const executed = remediation.status === "EXECUTED";
  const needsApproval = remediation.requires_approval && !executed;

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Recommended remediation</div>
          <h2 style={{ fontSize: 15 }}>{remediation.steps.length} steps</h2>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Pill
            label={`risk ${remediation.risk_level}`}
            tone={remediation.risk_level === "LOW" ? "pass" : "warn"}
          />
          <Pill label={remediation.status} />
        </div>
      </div>

      <div className="panel-body" style={{ paddingBottom: 0 }}>
        <p style={{ margin: "0 0 4px" }}>{remediation.diagnosis}</p>
        <p className="small muted" style={{ margin: 0 }}>
          {remediation.expected_result}
        </p>
      </div>

      <div className="panel-body tight" style={{ marginTop: 12 }}>
        {remediation.steps.map((step) => (
          <div className={`step${step.executed ? " done" : ""}`} key={step.id}>
            <div className="step-mark">{step.executed ? "✓" : ""}</div>
            <div>
              <div className="step-title">{step.title}</div>
              <div className="step-desc">{step.description}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="verdict">
        <div>
          <div className="mono small">
            {remediation.execution_mode === "SIMULATED"
              ? "Runs in a controlled simulation. No production system is modified."
              : "Real execution mode."}
          </div>
          {remediation.rollback ? (
            <div className="small muted" style={{ marginTop: 4 }}>
              Rollback: {remediation.rollback}
            </div>
          ) : null}
        </div>

        {executed ? (
          <Pill label="Executed" tone="pass" />
        ) : (
          <button
            type="button"
            className="btn accent"
            disabled={executing}
            onClick={() => onExecute(needsApproval)}
          >
            {executing
              ? "Applying…"
              : needsApproval
                ? "Approve and run simulation"
                : "Run simulation"}
          </button>
        )}
      </div>

      {needsApproval ? (
        <div className="panel-body" style={{ borderTop: "1px solid var(--line-soft)" }}>
          <p className="small" style={{ margin: 0 }}>
            This plan is above the low-risk threshold, so the backend refuses to run
            it until a human approves — the agent asking is not enough.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function VerificationPanel({ verification }: { verification: Verification }) {
  const tone = verification.status === "PASS" ? "pass" : "fail";
  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Verification</div>
          <h2 style={{ fontSize: 15 }}>{verification.summary}</h2>
        </div>
        <span className="small muted mono">{dateTime(verification.verified_at)}</span>
      </div>

      <div className="panel-body tight">
        {verification.checks.map((check) => (
          <div className="check" key={check.name}>
            <div>
              <div className="check-name">{check.name.replace(/_/g, " ")}</div>
              <div className="check-values">
                expected {String(check.expected)} · measured {String(check.actual)}
              </div>
            </div>
            <Pill label={check.status} />
          </div>
        ))}
      </div>

      <div className={`verdict ${tone}`}>
        <div>
          <div className="verdict-label">
            {verification.status === "PASS" ? "RESOLVED" : "NOT RESOLVED"}
          </div>
          <div className="small" style={{ marginTop: 2 }}>
            {verification.status === "PASS"
              ? "Every critical check passed, so the incident can close."
              : "A critical check failed. The incident stays open and the investigation reopens."}
          </div>
        </div>
        <Pill label={verification.status} tone={tone} />
      </div>
    </div>
  );
}

export function MemoryPanel({ memory }: { memory: MemoryReference | null }) {
  if (!memory) {
    return (
      <div className="panel">
        <div className="panel-body">
          <Empty
            title="Nothing written back yet"
            message="An investigation is only recorded once a verification has passed. That order is enforced by the backend."
          />
        </div>
      </div>
    );
  }

  const document = memory.document as Record<string, unknown>;

  return (
    <div className="memory">
      <div className="eyebrow">Knowledge captured</div>
      <h2 style={{ margin: "6px 0 14px" }}>
        Written back to DataHub as reusable context
      </h2>

      <dl className="kv">
        <dt>Pattern</dt>
        <dd className="mono">{memory.pattern}</dd>
        <dt>Root cause</dt>
        <dd>{memory.root_cause}</dd>
        <dt>Confidence</dt>
        <dd className="mono">{Math.round(memory.confidence * 100)}%</dd>
        <dt>Affected</dt>
        <dd className="mono">
          {Array.isArray(document.affected_assets) ? document.affected_assets.length : 0}{" "}
          assets
        </dd>
        <dt>Write status</dt>
        <dd>
          <Pill
            label={memory.write_back_status}
            tone={memory.write_back_status === "VERIFIED" ? "pass" : "warn"}
          />
        </dd>
      </dl>

      <div className="memory-ref">{memory.datahub_reference}</div>

      <p className="small" style={{ margin: "14px 0 0" }}>
        {memory.write_back_status === "LOCAL_ONLY" ? (
          <>
            DataHub refused the write, so the catalog was <b>not</b> enriched — the
            token most likely lacks tag-edit permission. The pattern was still
            learned here, so the next similar incident is recognised.
          </>
        ) : (
          <>
            The next incident on this asset starts by searching this record, so the
            same investigation is never run twice from scratch.
          </>
        )}
      </p>
    </div>
  );
}
