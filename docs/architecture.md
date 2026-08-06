# Architecture

## Principle

Simple first, extensible later. One repository, one deployable MVP, one reliable
investigation loop. No Kubernetes, no Kafka, no vector database, no multi-agent
orchestration. Infrastructure complexity would not make the agent smarter.

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ NEXT.JS UI                                                   │
│ Dashboard │ Investigation │ Impact │ Resolution & Memory      │
└──────────────────────────┬───────────────────────────────────┘
                REST + SSE │
┌──────────────────────────▼───────────────────────────────────┐
│ FASTAPI                                                      │
│ incidents · investigations · actions · memory · datahub       │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ INVESTIGATION AGENT                                          │
│                                                              │
│  ContextBuilder → EvidenceCollector → HypothesisEngine →     │
│  Scoring → CausalChain → BlastRadius → Remediation →         │
│  Verification → Memory                                       │
└──────────┬───────────────────────────────────┬───────────────┘
           │ typed tools                       │
┌──────────▼────────────────┐      ┌───────────▼───────────────┐
│ DataHub provider          │      │ PostgreSQL                │
│  live: MCP → GraphQL      │      │ incidents, investigations,│
│  fixture: local graph     │      │ evidence, hypotheses,     │
│  (every result labelled)  │      │ actions, verifications,   │
└───────────────────────────┘      │ memory refs, events, logs │
                                   └───────────────────────────┘
```

The UI holds no investigation logic. The API holds no reasoning. The agent holds
no persistence details. DataHub remains the authoritative context system;
PostgreSQL stores only what belongs to the application.

## Responsibility boundaries

| Component | Owns |
|---|---|
| `apps/web` | rendering incidents, the live timeline, evidence, impact, resolution |
| `apps/api/app/api` | HTTP contract, validation, idempotency, SSE transport |
| `apps/api/app/agents` | what context to fetch, evidence, hypotheses, scoring, causal chain |
| `apps/api/app/services` | scenario runtime, blast radius, remediation, verification, memory |
| `apps/api/app/domain` | invariants: state machines, risk policy, resolution rules |
| `apps/api/app/services/datahub` | the only place that talks to DataHub |

## The DataHub provider

Two implementations behind one abstract class:

- **`LiveDataHubProvider`** — MCP Streamable-HTTP as the primary path (JSON-RPC
  `initialize` / `tools/list` / `tools/call`, tolerant tool-name resolution),
  with GraphQL and the Timeline API as a fallback for anything MCP does not
  expose. Write-back creates a pattern tag, applies it to the affected assets,
  and adds an institutional-memory link, then reads it back to confirm.
- **`FixtureDataHubProvider`** — a deterministic graph loaded from
  `datahub/seed/showcase-ecommerce-demo.json`, mirroring the structure of the
  official datapacks with identical URN shapes.

`DATAHUB_MODE` selects: `live` (fail loudly), `fixture` (offline), `auto` (probe,
fall back, and label). Every `ToolResult` carries `source`, `source_system` and
`source_mode`, and those labels travel all the way to the UI badge. **The
fallback can never be mistaken for a live query.**

## Structural vs behavioural signals

A deliberate split that keeps the DataHub story honest:

| Signal | Source | Labelled |
|---|---|---|
| schema, lineage, ownership, governance, assertions definitions | DataHub | `DATAHUB` |
| metric readings, quality measurements, mapping status, pipeline runs | scenario runtime | `SCENARIO_RUNTIME` |
| the reported incident values | the incident report | `APPLICATION` |

Structural context always comes from the context graph. The behavioural
measurements a monitoring stack would emit come from a resettable, DB-backed
scenario world — which is also what makes the simulated remediation safe: it
mutates one `scenario_states` row and nothing else.

## The reasoning engine

Rule-based and deterministic. Rules describe *shapes* of signals, never
scenarios:

```
SCHEMA_DRIFT          supported by a schema change on a path to the target,
                      or an unresolved column mapping
                      (content quality corroborates only if one of those exists)
PIPELINE_FAILURE      supported by failed or late runs, contradicted by healthy ones
SOURCE_DATA_ANOMALY   supported by quality anomalies on graph source nodes
FRESHNESS_STALENESS   supported by freshness breaches or late runs
BUSINESS_SEASONALITY  contradicted by any high-relevance technical signal
```

Confidence, normalised 0–100 and always shown as a breakdown:

```
  evidence strength        max 30    relevance-weighted, symptom included
+ lineage relevance        max 25    shortest hop distance to the target
+ temporal correlation     max 20    does the cause precede the incident
+ cross-signal agreement   max 25    distinct corroborating evidence types
- contradicting evidence             8 / 4 / 2 by relevance
```

The symptom (`METRIC_CHANGE`) is excluded from cross-signal agreement: the thing
being explained cannot corroborate its own explanation. That single exclusion is
why the golden scenario scores 97 and not 100.

`CONFIRMED` requires all three of: score ≥ 85, at least two corroborating
evidence types, and at least one high-relevance causal signal. A loud single
signal is not corroboration.

## Organisational memory

Two layers, deliberately separate:

- **`memory_references`** — one row per resolved incident, plus the document
  written into DataHub. This is the record.
- **`knowledge_patterns`** — one row per *failure mode*, accumulated across
  every incident that produced it: occurrence count, symptom wordings, evidence
  signature, average confidence and trust, and the last **verified** remediation
  plan. This is the asset.

An unverified fix never updates the recommended plan, otherwise the library
would teach the next investigation something that failed. Pattern matching is
deliberately crude and inspectable — pattern name, asset overlap, symptom token
similarity — because a number a judge cannot reconstruct is worse than a simple
one.

The reuse rule is narrow on purpose: a plan is replayed only when the pattern
the agent *concluded* matches the one the library knows. Recognising a pattern
early must never let it pick the fix for a different conclusion.

## Trust versus confidence

| | Confidence | Trust |
|---|---|---|
| Question | how strongly does the evidence point here? | how grounded is this at all? |
| Range | 0–100, per hypothesis | 0–100, per investigation |
| Inputs | evidence strength, lineage relevance, temporal correlation, cross-signal agreement, contradictions | evidence quality, schema validation, lineage coverage, quality signals, historical match |
| Computed from | the hypothesis | the retrieved context |

`agents/trust.py` never reads the winning hypothesis' confidence, and a test
asserts that changing it leaves the trust score identical. Without that
independence the second number would just be the first one wearing a hat.

## Guardrails in code

| Rule | Where it lives |
|---|---|
| `RESOLVED` only after a passing verification | `domain/state_machine.py` transition table |
| No root cause without non-symptom evidence | `agents/investigator.py::_select_root_cause` |
| Risk classification and approval | `domain/action.py::assert_executable`, called by the API |
| Real production writes disabled | `ALLOW_REAL_REMEDIATION`, refused server-side |
| LLM proposals must cite real evidence | `agents/investigator.py::_llm_candidates` |
| Write-back validated before it leaves | `schemas/memory.py` + `services/memory.py` |
| No silent tool failure | `ToolResult.success` + `tool_failed` events |
| No secret in logs | `core/logging.py::redact` |
| A log line can never crash its caller | `core/logging.py::ContextLogger` |
| Unverified fixes stay out of the pattern library | `services/patterns.py::record` |
| Memory never shortcuts the investigation | `agents/investigator.py`, asserted in tests |

## Streaming

Server-Sent Events. Every event is persisted with a per-investigation sequence
number before being published, so a client can reconnect with `Last-Event-ID`,
replay what it missed, and continue — the subscription is opened *before* the
replay, so nothing falls between the two. The persisted event stream doubles as
the complete action log.

## Data model

Seven core entities — `Incident`, `Investigation`, `Evidence`, `Hypothesis`,
`Action`, `Verification`, `MemoryReference` — plus `KnowledgePattern`
(the accumulated failure modes), `InvestigationEvent`, `ToolCallLog`,
`ScenarioState` and `IdempotencyRecord`. DataHub assets are
referenced by URN only; the application never mirrors the context graph.

## Testing strategy

| Level | Covers |
|---|---|
| Unit | scoring components, state machines, risk policy, blast radius |
| Integration | fixture provider contract, context builder, write-back and its failure |
| End to end | all three scenarios, the HTTP golden path, SSE, guardrails |

The tests assert *properties*, not exact sentences: evidence types present,
confidence thresholds, a confirmed hypothesis existing, verification passing —
so improving the wording of an explanation never breaks the suite.
