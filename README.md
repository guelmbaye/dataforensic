<p align="center">
  <img src="apps/web/public/logo.png" alt="DATAFORENSIC AI" width="420">
</p>

<h1 align="center">DATAFORENSIC AI</h1>

<p align="center"><strong>The organizational memory engine for DataHub.</strong></p>

> Every incident investigated. Every lesson remembered. Every future incident resolved faster.

DATAFORENSIC AI takes a data incident — *"revenue dropped 18.5%"* — and runs the
whole operational loop a data engineer would run by hand: it pulls context from
DataHub, traces lineage, collects evidence, scores competing hypotheses, names a
probable root cause, computes the blast radius, proposes and executes a safe
remediation, and verifies the outcome.

Then it does the part that makes it a system rather than an assistant: it turns
the finished investigation into a **knowledge pattern** written back into
DataHub, so the organisation gets measurably better at the next incident.

```
Incident → Context → Evidence → Root Cause → Impact → Remediation → Verification
                                                                        ↓
                        future incidents start here  ←  Knowledge Pattern
```

**Hackathon:** DataHub Agent Hackathon 2026 · **Category:** Agents That Do Real Work

---

## The problem

When data breaks, the visible symptom is far from the cause. A revenue number
moves, and someone has to reconstruct, by hand and under pressure: which dataset
feeds it, which pipeline writes it, what changed upstream, what else consumes
it, who owns those assets, and what a safe fix looks like. That reconstruction
is repeated from scratch every time, because the reasoning ends up scattered
across tickets, Slack threads and individual memory.

## The solution

The context needed for that reconstruction already exists — in DataHub. What is
missing is an agent that reasons *through* it and gives the knowledge back.

| Existing tool | Does | DATAFORENSIC adds |
|---|---|---|
| Data catalog | describes data | investigates incidents |
| Lineage | shows relationships | reasons over relationships |
| Data quality | detects anomalies | finds probable causes |
| SQL copilot | generates queries | runs investigations |
| Observability | detects failures | connects failures to business context |
| Generic AI agent | executes tools | builds persistent incident memory |

## The organisational learning loop

Traditional incident management ends when the issue is resolved, and the
reasoning evaporates into a ticket. Here, a resolved investigation is folded
into a pattern library that lives in DataHub:

| | First time a failure mode is seen | Once it is known |
|---|---|---|
| Precedent | none | matched before any work starts, with a similarity score |
| Remediation | generated from evidence | the plan that was **verified** last time, replayed |
| Trust score | 85 / 100 | 100 / 100 — a confirmed precedent is a grounding signal |
| Evidence | gathered from scratch | gathered from scratch **again** |

That last row is the important one. Memory accelerates the investigation; it
never replaces it. A recognised pattern arrives as a lead, the agent still walks
lineage, still collects its own evidence, still scores every alternative, and
still has to verify before anything resolves — so a pattern that does not
actually fit simply fails to be confirmed. There is a test named after exactly
that.

Every investigation also records what it cost — DataHub calls and wall-clock
reasoning time — so the claim that memory helps is measured rather than
asserted.

## The trust score

Confidence answers *how strongly does the evidence point at this cause?*
Trust answers a different and, for an AI system, more important question:
*how much of this investigation is actually grounded in retrieved context?*

```
Evidence quality      30    breadth and weight of independent signals
Schema validation     20    does the field named by the conclusion exist
Lineage coverage      20    both directions walked, no signal from outside the graph
Quality signals       15    declared checks and measured anomalies agree
Historical match      15    a previous investigation reached the same conclusion
```

The two scores are allowed to disagree, and that is the point: an investigation
can be 97% confident and barely grounded — which is exactly what a thin context
and a lucky correlation look like. The trust score is computed without ever
reading the winning hypothesis' confidence, and there is a test that proves it.

It also earns its keep. The first version of the golden scenario scored 85 with
schema validation only partial, because the agent named `discount_amount`
without ever reading the schema of the asset holding it. The fix was not to
soften the check — it was to make the agent read upstream schemas.

## Why DataHub

DataHub is not a data source rendered by the UI. **It is the context layer the
agent reasons through.** The agent reads:

- **asset context** — platform, domain, description, criticality, governance
- **schemas** — of the affected asset *and* of the upstream assets close enough
  to be implicated, so a field-level conclusion is never unverified
- **lineage** — upstream to find the cause, downstream to size the impact
- **ownership** — to know who has to act
- **quality context** — assertions and their run history
- **related assets** — domain, tag and glossary neighbours
- **change history** — the timeline that makes temporal correlation possible

…and writes back a complete investigation knowledge object: root cause,
evidence, **the hypotheses that were rejected**, blast radius, remediation,
verification, confidence and trust score — attached to the affected assets,
tagged with its pattern, and retrievable by the next investigation.

## How it works

```
                         ┌──────────────────────────────┐
   Incident  ──────────► │      INVESTIGATION AGENT     │
                         │                              │
                         │  context → evidence →        │
                         │  hypotheses → scoring →      │
                         │  root cause → blast radius → │
                         │  remediation → verification  │
                         └───────┬──────────────┬───────┘
                    typed tools  │              │  application state
                                 ▼              ▼
                   ┌───────────────────┐  ┌──────────────┐
                   │ DataHub MCP Server│  │  PostgreSQL  │
                   │  → Context Graph  │  │  investigation│
                   │  ← Incident memory│  │  evidence …  │
                   └───────────────────┘  └──────────────┘
```

Five rules are enforced by the code, not by the prompt:

1. **Evidence before inference.** A hypothesis supported only by the symptom is
   never published as a root cause — the investigation blocks instead.
2. **No hidden actions.** Every tool call is logged and streamed to the timeline.
3. **No silent failure.** A tool that fails returns an explicit error; it never
   returns an empty list that reads like "nothing found".
4. **No destructive autonomy.** Risk is classified server-side. Medium and high
   risk actions require explicit approval; real production writes are disabled
   by configuration and refused even when the agent asks.
5. **No false verification.** `RESOLVED` is unreachable in the state machine
   except through a passing verification.

## Quick start

```bash
git clone <repository>
cd dataforensic-ai
cp .env.example .env
docker compose up -d
./scripts/seed-demo.sh
```

Then open **http://localhost:3000** (UI) or **http://localhost:8000/docs** (API).

With a real DataHub instance, start it alongside and point `.env` at it:

```bash
uvx --from acryl-datahub datahub docker quickstart
uvx --from acryl-datahub datahub init --username datahub --password datahub
uvx --from acryl-datahub datahub datapack load showcase-ecommerce
```

Then point `.env` at it and set `DATAHUB_MODE=live`. Full walkthrough, including
the MCP bridge, in [`docs/DEPLOY-DIGITALOCEAN.md`](docs/DEPLOY-DIGITALOCEAN.md).

### Running without DataHub

`DATAHUB_MODE=auto` probes the live instance and, if it is unreachable, falls
back to a deterministic context graph shipped in `datahub/seed/`. **The fallback
never claims to be live DataHub**: every tool result, every evidence item, every
API response and the UI badge carry `source_mode: DEMO_FIXTURE` instead of
`LIVE_DATAHUB`. Set `DATAHUB_MODE=live` to make an unreachable DataHub a hard
failure instead.

## Demo scenario

**Incident:** revenue on `sales_daily` is $10.1M instead of $12.4M (−18.5%).
The cause is not given to the agent.

What the agent finds, in order:

| Step | Result |
|---|---|
| Context | asset + schema + 4 upstream / 5 downstream lineage + ownership + assertions |
| Evidence | 11 signals, each with its source and timestamp |
| Root cause | `SCHEMA_DRIFT` — **97%** (evidence 30 + lineage 25 + temporal 20 + cross-signal 22) |
| Causal chain | ERP rename `discount_amount → discount_value` → mapping unresolved → NULL discounts → `orders_enriched` corrupted → revenue −18.5% |
| Blast radius | **9 assets · 7 consumers · 3 owners** — 4 datasets, 3 dashboards, 2 ML models |
| Remediation | 5 steps, risk LOW, executed in a controlled simulation |
| Verification | **7 / 7 checks PASS** — mapping, NULL rate, revenue, variance, downstream, context, assertions |
| Trust | **85 / 100** — high confidence, with the one partial check named |
| Memory | written back to DataHub as a knowledge pattern, found again by the next similar incident |

Run the same incident a second time and the difference is visible without
narration: the pattern is recognised before any work starts, the verified
remediation is replayed instead of regenerated, and the trust score reaches 100
because a confirmed precedent now exists.

Two more scenarios run on the **same generic engine** with no scenario-specific
code, which is what proves the reasoning is real:

| Scenario | Signals present | Conclusion |
|---|---|---|
| `revenue-collapse` | schema change + broken mapping + content quality | `SCHEMA_DRIFT` 97% |
| `pipeline-freshness` | freshness breach + late run, **no schema change** | `FRESHNESS_STALENESS` 92% |
| `healthcare-quality` | quality anomaly on a source asset, **healthy mapping** | `SOURCE_DATA_ANOMALY` 86% |

Remove the schema-change evidence from the first scenario and `SCHEMA_DRIFT`
collapses on its own — there is a test for exactly that.

## Sample outputs

`examples/` contains the real artefacts of a full run, regenerated with
`python3 scripts/generate-examples.py`:

```
examples/
├── investigation.json           complete agent output contract
├── evidence.json                every signal with source + provenance
├── hypotheses.json              all candidates with score breakdowns
├── blast-radius.json            impact computed from lineage
├── remediation.json             plan, risk, execution result
├── verification.json            the 7 checks
├── memory.json                  the document written back to DataHub
├── trust-score.json             the five grounding checks
├── learning.json                what the investigation cost
├── knowledge-patterns.json      the pattern library after the run
└── investigation-timeline.json  the streamed events
```

## The interface

Five screens: the incident queue, the investigation workspace, the impact view,
the resolution & memory view, and the pattern library — what this DataHub has
learned so far.

The workspace is built as a laboratory record rather than a BI dashboard.
Monospace carries everything that was *measured* — URNs, field names, numbers,
timestamps — and the sans-serif carries only what a human wrote. Two devices do
the explaining:

- **The score shows its work.** The confidence number is rendered as a stacked
  bar of the four components that produced it, with contradictions subtracted
  visibly. `30 + 25 + 20 + 22 − 0 = 97` is on screen, so the number can be
  argued with rather than believed.
- **Evidence outranks prose.** Each signal has a left rail whose thickness
  encodes its relevance, so weight is readable before a word is, and every item
  states which system observed it.
- **Trust is shown check by check**, never as a bare number, so a partial or
  failed grounding check is as visible as the score itself.

The timeline streams over SSE and follows the agent, but stops following the
moment you scroll up — and while the agent works it says what it is doing
("Querying DataHub context", "Walking downstream lineage") rather than showing a
spinner. The context-source badge in the header is never inferred: it renders
exactly what the API reports, so a demo run on the fallback graph cannot be
mistaken for a live one.

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` if the API is not on `http://localhost:8000/api/v1`.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 + React 19 + TypeScript (no UI framework, hand-written CSS tokens) |
| Backend | Python + FastAPI |
| Agent | Python, typed tools, deterministic scoring engine |
| DataHub | MCP Server (primary) + GraphQL/Timeline fallback |
| Database | PostgreSQL (SQLite for tests) |
| Streaming | Server-Sent Events |
| Deployment | Docker Compose |

Every DataHub-specific claim in this repository — tool names, API paths,
parameters, URN shapes — was checked against the official documentation, and
[`docs/datahub-api-verification.md`](docs/datahub-api-verification.md) records
what is verified and what is not.

See [`docs/architecture.md`](docs/architecture.md) for the detailed design,
[`docs/demo.md`](docs/demo.md) for the demo runbook, and
[`docs/DEPLOY-DIGITALOCEAN.md`](docs/DEPLOY-DIGITALOCEAN.md) to put it behind a
domain.

### About the LLM

`LLM_PROVIDER=none` by default. The deterministic engine always decides. An LLM,
when configured, may only propose *additional* candidate hypotheses that cite
evidence IDs the agent actually collected — proposals citing nothing are
discarded and the rejection is logged to the timeline. This keeps the demo
reproducible and keeps the reasoning auditable.

## Tests

```bash
cd apps/api && pytest
```

116 tests covering state-machine invariants, the confidence formula, blast-radius
derivation, the DataHub provider contract, all three scenarios end to end, the
HTTP golden path with SSE, and the failure modes: DataHub unavailable →
`BLOCKED` with no invented cause; verification `FAIL` → never `RESOLVED`;
write-back failure → reported, not hidden; high-risk action → refused without
approval; an unverified fix → never promoted into the pattern library; a
recognised pattern → never allowed to shortcut the investigation.

## Open source contribution

`datahub/skills/incident-investigation/` packages the reusable part of this work
as a DataHub Skill: gather asset context, trace lineage both ways, collect
recent changes, summarise downstream impact, and validate an investigation
write-back document. It deliberately does not decide root causes and does not
write to DataHub — scoring stays with the agent, and performing the write stays
with the caller. It has no dependency on DATAFORENSIC AI and ships with 10 tests
that run against an in-memory fake.

**Upstream status: prepared, not yet submitted.** Nothing here claims a
contribution that has not been made.

## Submission

[`SUBMISSION.md`](SUBMISSION.md) holds the Devpost description, the form fields,
the mapping from each judging criterion to something a judge can verify, and the
pre-submission checklist. [`docs/video-script.md`](docs/video-script.md) is the
shot-by-shot script for the demo video.

## Brand assets

`brand/logo-master.png` is the single source of truth. Every derived asset — the
light and dark lockups, the mark, the favicon and the app icons — is generated
from it:

```bash
python3 scripts/build-brand-assets.py
```

The dark variant is not a separate drawing: the script flips only the neutral
half of the wordmark to white, leaving the blue and the orange exactly as
designed. It is restricted to the wordmark on purpose — the mark contains white
circuit lines, and inverting the whole image would turn them black.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
