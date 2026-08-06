/** Presentation helpers. Nothing here decides anything — it only formats. */

export function assetName(urn: string | null | undefined): string {
  if (!urn) return "unknown asset";
  const match = urn.match(/,([^,]+),[^,]*\)$/);
  if (match) return match[1];
  const tail = urn.split(":").pop() ?? urn;
  return tail.replace(/[()]/g, "");
}

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "--:--:--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString([], {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Turns SCHEMA_CHANGE into "Schema change" for prose contexts. */
export function humanise(token: string | null | undefined): string {
  if (!token) return "";
  const lower = token.replace(/_/g, " ").toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

export function verdictClass(status: string | null | undefined): string {
  switch ((status ?? "").toUpperCase()) {
    case "PASS":
    case "RESOLVED":
    case "COMPLETED":
    case "CONFIRMED":
    case "VERIFIED":
      return "pass";
    case "FAIL":
    case "FAILED":
    case "REJECTED":
      return "fail";
    case "PARTIAL":
    case "BLOCKED":
    case "WEAKENED":
    case "NEEDS_HUMAN":
      return "warn";
    case "RUNNING":
    case "INVESTIGATING":
    case "REMEDIATING":
    case "VERIFYING":
    case "SUPPORTED":
      return "accent";
    default:
      return "idle";
  }
}

/**
 * What the agent is doing right now, phrased as work rather than as "Loading…".
 * The spec is explicit about this: a spinner hides the reasoning, a sentence
 * shows it.
 */
export const PHASE_ACTIVITY: Record<string, string> = {
  CREATED: "Starting the investigation",
  CONTEXT_LOADING: "Querying DataHub context",
  INVESTIGATING: "Correlating evidence signals",
  HYPOTHESIS_TESTING: "Testing competing hypotheses",
  ROOT_CAUSE_IDENTIFIED: "Tracing the causal chain",
  IMPACT_ANALYSIS: "Walking downstream lineage",
  REMEDIATION_PLANNED: "Preparing the remediation plan",
  REMEDIATION_EXECUTED: "Applying the controlled simulation",
  VERIFYING: "Verifying the resolution",
  RESOLVED: "Writing the investigation back",
  MEMORY_WRITTEN: "Investigation complete",
};

/** Events that deserve a heavier mark on the timeline spine. */
export const MILESTONE_EVENTS = new Set([
  "investigation_started",
  "root_cause_identified",
  "blast_radius_calculated",
  "remediation_executed",
  "verification_completed",
  "incident_resolved",
  "memory_written",
  "investigation_completed",
  "investigation_blocked",
  "investigation_failed",
]);
