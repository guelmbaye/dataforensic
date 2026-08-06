"use client";

import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { IncidentSummary } from "@/lib/types";

export function NewIncidentDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (incident: IncidentSummary) => void;
}) {
  const [form, setForm] = useState({
    title: "",
    description: "",
    asset_urn: "",
    severity: "HIGH",
    observed_value: "",
    expected_value: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (key: keyof typeof form) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = async () => {
    setError(null);
    if (!form.title.trim() || !form.asset_urn.trim()) {
      setError("A title and a DataHub asset URN are required.");
      return;
    }
    if (!form.asset_urn.startsWith("urn:li:")) {
      setError("The asset must be identified by a DataHub URN, starting with urn:li:");
      return;
    }
    setSaving(true);
    try {
      const created = await api.createIncident({
        ...form,
        description: form.description || form.title,
      });
      onCreated(created);
    } catch (err) {
      setError((err as ApiError).message);
      setSaving(false);
    }
  };

  return (
    <div
      className="backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Report an incident"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="dialog">
        <div className="panel-head">
          <div>
            <div className="eyebrow">New incident</div>
            <h2 style={{ fontSize: 16 }}>What went wrong?</h2>
          </div>
        </div>

        <div className="panel-body">
          <div className="field">
            <label htmlFor="title">Title</label>
            <input
              id="title"
              value={form.title}
              onChange={set("title")}
              placeholder="Revenue anomaly on sales_daily"
              autoFocus
            />
          </div>

          <div className="field">
            <label htmlFor="description">What was observed</label>
            <textarea
              id="description"
              value={form.description}
              onChange={set("description")}
              placeholder="Daily revenue dropped unexpectedly. Find out what happened and what is affected."
            />
          </div>

          <div className="field">
            <label htmlFor="urn">Affected asset (DataHub URN)</label>
            <input
              id="urn"
              value={form.asset_urn}
              onChange={set("asset_urn")}
              placeholder="urn:li:dataset:(urn:li:dataPlatform:snowflake,ANALYTICS.SALES_DAILY,PROD)"
            />
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="observed">Observed value</label>
              <input
                id="observed"
                value={form.observed_value}
                onChange={set("observed_value")}
                placeholder="$10.1M"
              />
            </div>
            <div className="field">
              <label htmlFor="expected">Expected value</label>
              <input
                id="expected"
                value={form.expected_value}
                onChange={set("expected_value")}
                placeholder="$12.4M"
              />
            </div>
          </div>

          <div className="field">
            <label htmlFor="severity">Severity</label>
            <select id="severity" value={form.severity} onChange={set("severity")}>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
            </select>
          </div>

          {error ? (
            <p className="small" style={{ color: "var(--fail)", margin: 0 }}>
              {error}
            </p>
          ) : null}
        </div>

        <div className="dialog-foot">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn accent" onClick={submit} disabled={saving}>
            {saving ? "Starting…" : "Start investigation"}
          </button>
        </div>
      </div>
    </div>
  );
}
