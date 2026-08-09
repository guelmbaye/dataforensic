"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { NewIncidentDialog } from "@/components/NewIncidentDialog";
import { Empty, ErrorState, Pill, Skeleton } from "@/components/Primitives";
import { ApiError, api } from "@/lib/api";
import { dateTime, verdictClass } from "@/lib/format";
import type { IncidentSummary, ScenarioSummary } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const [incidents, setIncidents] = useState<IncidentSummary[] | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [starting, setStarting] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .listIncidents()
      .then((page) => setIncidents(page.items))
      .catch((err: ApiError) => setError(err));
    api
      .listScenarios()
      .then((page) => setScenarios(page.items))
      .catch(() => setScenarios([]));
  }, []);

  useEffect(load, [load]);

  const investigate = async (incident: IncidentSummary) => {
    setStarting(incident.id);
    try {
      const started = await api.investigate(incident.id);
      router.push(`/investigations/${started.investigation_id}`);
    } catch (err) {
      setError(err as ApiError);
      setStarting(null);
    }
  };

  const open = (incident: IncidentSummary) => {
    if (incident.investigation_id) {
      router.push(`/investigations/${incident.investigation_id}`);
    } else {
      void investigate(incident);
    }
  };

  return (
    <main className="shell page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Incident queue</div>
          <h1>Something broke. Find out why.</h1>
          <p>
            Hand the agent an incident and it works the whole loop: pull context from
            DataHub, gather evidence, name a probable cause, size the impact, fix it
            safely, verify, and record what it learned.
          </p>
        </div>
        <button type="button" className="btn" onClick={() => setDialogOpen(true)}>
          Report an incident
        </button>
      </div>

      {error ? (
        <ErrorState
          title="Cannot load incidents"
          message={error.message}
          code={error.code}
          onRetry={load}
        />
      ) : null}

      <div className="panel">
        <div className="panel-head">
          <div className="eyebrow">Active and past incidents</div>
          <span className="small muted">{incidents?.length ?? 0} total</span>
        </div>

        <div className="panel-body tight">
          {incidents === null && !error ? (
            <div style={{ padding: 16, display: "grid", gap: 10 }}>
              <Skeleton height={44} />
              <Skeleton height={44} />
            </div>
          ) : null}

          {incidents?.length === 0 ? (
            <Empty
              title="No incidents yet"
              message="Report one, or load a prepared scenario below."
            >
              <button type="button" className="btn" onClick={() => setDialogOpen(true)}>
                Report an incident
              </button>
            </Empty>
          ) : null}

          {incidents?.map((incident) => (
            <div className="incident-row" key={incident.id}>
              <div className={`incident-rail ${incident.severity}`} />
              <div className="incident-main">
                <div className="incident-title">
                  <h3>{incident.title}</h3>
                  <Pill
                    label={incident.status}
                    tone={verdictClass(incident.status)}
                    running={incident.investigation_status === "RUNNING"}
                  />
                  <Pill label={incident.severity} tone="idle" />
                </div>

                <div className="incident-meta">
                  <span className="urn">{incident.asset_name}</span>
                  {incident.observed_value && incident.expected_value ? (
                    <span className="delta">
                      observed <b>{incident.observed_value}</b> · expected{" "}
                      {incident.expected_value}
                    </span>
                  ) : null}
                  <span className="small muted">{dateTime(incident.created_at)}</span>
                </div>

                {incident.root_cause_summary ? (
                  <p className="small" style={{ margin: "8px 0 0", color: "var(--ink-2)" }}>
                    {incident.root_cause_summary}
                    {incident.confidence ? (
                      <span className="mono muted">
                        {" "}
                        · {Math.round(incident.confidence * 100)}%
                      </span>
                    ) : null}
                  </p>
                ) : null}
              </div>

              <div className="incident-action">
                <button
                  type="button"
                  className={incident.investigation_id ? "btn ghost" : "btn accent"}
                  disabled={starting === incident.id}
                  onClick={() => open(incident)}
                >
                  {starting === incident.id
                    ? "Starting…"
                    : incident.investigation_id
                      ? "Open investigation"
                      : "Investigate"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {scenarios.length ? (
        <div className="panel">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Prepared scenarios</div>
              <h2 style={{ fontSize: 15 }}>Reproducible incidents</h2>
            </div>
            <span className="small muted">
              The cause is never given to the agent
            </span>
          </div>
          <div className="panel-body tight">
            {scenarios.map((scenario) => (
              <div className="asset" key={scenario.id}>
                <div className="asset-hop">{scenario.state === "BROKEN" ? "✕" : "✓"}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="asset-name">{scenario.title}</div>
                  <div className="asset-kind">{scenario.id}</div>
                </div>
                <button
                  type="button"
                  className="btn ghost small"
                  onClick={async () => {
                    try {
                      // A prepared scenario is only reproducible if its world
                      // starts broken. After a previous run it is remediated,
                      // and the agent would correctly find nothing to explain.
                      await api.resetScenario(scenario.id);
                      const created = await api.createIncident({
                        title: scenario.incident_template.title,
                        description: scenario.incident_template.description,
                        asset_urn: scenario.incident_template.asset_urn,
                        severity: scenario.incident_template.severity ?? "HIGH",
                        observed_value: scenario.incident_template.observed_value,
                        expected_value: scenario.incident_template.expected_value,
                        detected_at: scenario.incident_template.detected_at,
                      });
                      await investigate(created);
                    } catch (err) {
                      setError(err as ApiError);
                    }
                  }}
                >
                  Load and investigate
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {dialogOpen ? (
        <NewIncidentDialog
          onClose={() => setDialogOpen(false)}
          onCreated={(incident) => {
            setDialogOpen(false);
            void investigate(incident);
          }}
        />
      ) : null}
    </main>
  );
}
