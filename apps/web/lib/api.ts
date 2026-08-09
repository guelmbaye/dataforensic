import type {
  DataHubStatus,
  KnowledgePattern,
  IncidentDetail,
  IncidentSummary,
  Investigation,
  InvestigationEvent,
  Remediation,
  ScenarioSummary,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  code: string;
  retryable: boolean;

  constructor(message: string, code = "UNKNOWN", retryable = false) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.retryable = retryable;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(
      "The investigation service is not reachable. Check that the API is running.",
      "API_UNREACHABLE",
      true,
    );
  }

  if (!response.ok) {
    let code = "UNKNOWN";
    let message = `Request failed (${response.status})`;
    let retryable = response.status >= 500;
    try {
      const body = await response.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        retryable = Boolean(body.error.retryable);
      }
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(message, code, retryable);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface NewIncident {
  title: string;
  description: string;
  asset_urn: string;
  severity: string;
  observed_value?: string;
  expected_value?: string;
  detected_at?: string;
}

export const api = {
  health: () => request<{ status: string; datahub: DataHubStatus }>("/health"),
  datahubStatus: () => request<DataHubStatus>("/datahub/status"),

  listIncidents: () =>
    request<{ items: IncidentSummary[]; total: number }>("/incidents"),
  getIncident: (id: string) => request<IncidentDetail>(`/incidents/${id}`),
  createIncident: (payload: NewIncident) =>
    request<IncidentSummary>("/incidents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  investigate: (id: string, force = false) =>
    request<{ investigation_id: string; status: string; stream_url: string }>(
      `/incidents/${id}/investigate${force ? "?force=true" : ""}`,
      { method: "POST" },
    ),

  getInvestigation: (id: string) => request<Investigation>(`/investigations/${id}`),
  getEvents: (id: string) =>
    request<InvestigationEvent[]>(`/investigations/${id}/events`).catch(() => []),

  executeAction: (actionId: string, approved: boolean) =>
    request<Remediation>(`/actions/${actionId}/execute`, {
      method: "POST",
      body: JSON.stringify({ approved, approved_by: approved ? "demo-operator" : null }),
    }),

  listPatterns: () =>
    request<{ items: KnowledgePattern[]; total: number }>("/patterns"),
  getPattern: (pattern: string) =>
    request<KnowledgePattern>(`/patterns/${encodeURIComponent(pattern)}`),

  resetScenario: (id: string) =>
    request<Record<string, unknown>>(`/scenarios/${encodeURIComponent(id)}/reset`, {
      method: "POST",
    }),

  listScenarios: () =>
    request<{ items: ScenarioSummary[] }>("/scenarios"),
  resetDemo: () => request<Record<string, unknown>>("/demo/reset", { method: "POST" }),
};

export function streamUrl(investigationId: string, lastSeq = 0): string {
  return `${API_URL}/investigations/${investigationId}/events?lastEventId=${lastSeq}`;
}
