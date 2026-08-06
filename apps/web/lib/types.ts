/** Mirrors the FastAPI response contract (apps/api/app/schemas). */

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type SourceMode = "LIVE_DATAHUB" | "DEMO_FIXTURE";

export interface Owner {
  urn?: string | null;
  name?: string | null;
  email?: string | null;
  type?: string | null;
  assets?: string[];
}

export interface IncidentSummary {
  id: string;
  title: string;
  asset_urn: string;
  asset_name: string;
  severity: Severity;
  status: string;
  observed_value: string | null;
  expected_value: string | null;
  scenario_id: string | null;
  created_at: string;
  resolved_at: string | null;
  investigation_id: string | null;
  investigation_status: string | null;
  root_cause_summary: string | null;
  confidence: number | null;
}

export interface IncidentDetail extends IncidentSummary {
  description: string;
  detected_at: string | null;
  blocked_reason: string | null;
  root_cause_pattern: string | null;
  blast_radius: BlastRadius | Record<string, never>;
  verification_status: string | null;
  datahub_source_mode: string | null;
  memory: {
    datahub_reference: string;
    pattern: string | null;
    write_back_status: string;
    source_mode: string;
  } | null;
}

export interface Evidence {
  id: string;
  type: string;
  source: string;
  source_system: string;
  source_mode: SourceMode;
  asset_urn: string | null;
  field_path: string | null;
  observation: string;
  relevance: "LOW" | "MEDIUM" | "HIGH";
  observed_at: string | null;
  lineage_distance: number | null;
  metadata: Record<string, unknown>;
}

export interface ScoreBreakdown {
  evidence_strength?: number;
  lineage_relevance?: number;
  temporal_correlation?: number;
  cross_signal_agreement?: number;
  contradicting_evidence?: number;
  total?: number;
}

export interface Hypothesis {
  id: string;
  pattern: string;
  description: string;
  confidence: number;
  status: "UNTESTED" | "SUPPORTED" | "WEAKENED" | "REJECTED" | "CONFIRMED";
  reasoning_summary: string;
  score_breakdown: ScoreBreakdown;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  proposed_by: string;
  is_primary: boolean;
}

export interface CausalStep {
  step: number;
  label: string;
  detail: string;
  asset_urn: string | null;
  asset_name: string | null;
  evidence_ids: string[];
  evidence_type: string;
}

export interface AffectedAsset {
  urn: string;
  name: string;
  entity_type: string;
  platform: string | null;
  distance: number | null;
  criticality: string;
  tags: string[];
  bucket: string;
  owners: Owner[];
}

export interface BlastRadius {
  origin_urn: string;
  origin_name: string | null;
  counts: Record<string, number>;
  total_affected_assets: number;
  consumers: number;
  owners: Owner[];
  owner_count: number;
  risk_level: string;
  risk_score: number;
  risk_factors: string[];
  critical_assets: { urn: string; name: string; reason: unknown }[];
  affected_assets: AffectedAsset[];
  computed_from: Record<string, unknown>;
}

export interface RemediationStep {
  id: string;
  title: string;
  description: string;
  risk: string;
  effect: string | null;
  executed: boolean;
  result: Record<string, unknown> | null;
}

export interface Remediation {
  action_id: string;
  investigation_id: string;
  type: string;
  status: string;
  diagnosis: string;
  steps: RemediationStep[];
  risk_level: string;
  requires_approval: boolean;
  execution_mode: string;
  expected_result: string;
  rollback: string;
  notify_owners: string[];
  executed_at: string | null;
  result: Record<string, unknown> | null;
}

export interface Check {
  name: string;
  status: "PASS" | "FAIL" | "PARTIAL";
  critical: boolean;
  expected: unknown;
  actual: unknown;
  detail: string;
  asset_urn: string | null;
}

export interface Verification {
  id: string;
  investigation_id: string;
  status: "PASS" | "FAIL" | "PARTIAL";
  summary: string;
  passed: number;
  total: number;
  checks: Check[];
  verified_at: string;
}

export interface MemoryReference {
  id: string;
  incident_id: string;
  investigation_id: string;
  datahub_reference: string;
  write_back_status: string;
  source_mode: string;
  pattern: string | null;
  root_cause: string | null;
  confidence: number;
  created_at: string;
  document: Record<string, unknown>;
}

export interface TrustCheck {
  key: string;
  label: string;
  status: "PASS" | "PARTIAL" | "FAIL";
  points: number;
  max_points: number;
  detail: string;
}

export interface TrustScore {
  score: number;
  max_score: number;
  decision:
    | "HIGH_CONFIDENCE"
    | "MODERATE_CONFIDENCE"
    | "LOW_CONFIDENCE"
    | "INSUFFICIENT_GROUNDING";
  rationale: string;
  checks: TrustCheck[];
}

export interface Learning {
  memory_assisted: boolean;
  matched_pattern: string | null;
  reused_from_investigation_id: string | null;
  remediation_source: string | null;
  duration_ms: number;
  tool_call_count: number;
}

export interface PatternMatch {
  pattern: string;
  label: string;
  similarity: number;
  occurrences: number;
  average_confidence: number;
  average_trust_score: number;
  verified_resolutions: number;
  symptoms: string[];
  evidence_signature: string[];
  recommended_remediation: string[];
  last_seen: string | null;
  match_reasons: string[];
}

export interface KnowledgePattern {
  pattern: string;
  label: string;
  description: string;
  occurrences: number;
  verified_resolutions: number;
  first_seen: string | null;
  last_seen: string | null;
  symptoms: string[];
  evidence_signature: string[];
  resolution_steps: string[];
  affected_asset_urns: string[];
  average_confidence: number;
  average_trust_score: number;
  first_investigation_ms: number | null;
  latest_investigation_ms: number | null;
  first_investigation_tool_calls: number | null;
  latest_investigation_tool_calls: number | null;
  history: Record<string, unknown>[];
}

export interface Investigation {
  id: string;
  incident_id: string;
  status: "RUNNING" | "COMPLETED" | "FAILED" | "BLOCKED";
  phase: string;
  started_at: string;
  completed_at: string | null;
  datahub_source_mode: SourceMode | null;
  reasoning_engine: string | null;
  blocked_reason: string | null;
  error: string | null;
  context: Record<string, unknown>;
  trust: TrustScore | Record<string, never>;
  learning: Learning;
  root_cause: {
    summary: string | null;
    pattern: string | null;
    confidence: number;
    reasoning: string;
    score_breakdown: ScoreBreakdown;
    evidence_ids: string[];
  };
  causal_chain: CausalStep[];
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  blast_radius: BlastRadius | Record<string, never>;
  remediation: Remediation | null;
  verification: Verification | null;
  memory: MemoryReference | null;
}

export interface InvestigationEvent {
  seq: number;
  event: string;
  level: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
  investigation_id: string;
}

export interface DataHubStatus {
  mode: string;
  source_mode: string;
  provider: string;
  connected: boolean;
  datahub_url: string | null;
  mcp_url: string | null;
  write_back_enabled: boolean;
  detail: string;
  tools: string[];
}

export interface ScenarioSummary {
  id: string;
  title: string;
  target_asset_urn: string | null;
  incident_time: string | null;
  state: string;
  incident_template: Record<string, string>;
}

export interface ApiErrorBody {
  error: { code: string; message: string; retryable: boolean; details?: unknown };
}
