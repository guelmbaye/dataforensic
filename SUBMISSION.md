# Submission pack — Build with DataHub: The Agent Hackathon

Everything needed to fill the Devpost form. Copy the blocks marked **paste**
straight into the corresponding field.

- **Deadline:** August 10, 2026 — 5:00pm EDT
- **Judging period:** August 17 – 31, 2026
- **Category:** Agents That Do Real Work

> **The instance must stay up until August 31, not August 10.** The rules
> require the project to remain free and unrestricted for testing *until the
> judging period ends*. A demo taken down the day after submission is a
> disqualifying detail that costs nothing to avoid.

---

## 1. Form fields

| Field | Value |
|---|---|
| Project name | **DATAFORENSIC AI** |
| Tagline | The organizational memory engine for DataHub — an agent that investigates data incidents, proves the cause with evidence, and turns every resolution into reusable knowledge |
| Category | Agents That Do Real Work |
| Project URL (testing) | `https://dataforensic.vylantic.com` |
| DataHub instance (in the description, not the form) | `https://datahub.dataforensic.vylantic.com` |
| Repository URL | `https://github.com/<org>/dataforensic-ai` (public, Apache 2.0) |
| Video URL | `https://youtu.be/<id>` (public, under 3 minutes) |
| Built with | `python` `fastapi` `nextjs` `react` `typescript` `postgresql` `docker` `datahub` `mcp` `sse` |
| DataHub integration | MCP Server (primary) + GraphQL / Timeline API fallback + a reusable DataHub Skill |

**Testing instructions** (paste into the testing field):

> No login required. Open `https://dataforensic.vylantic.com`, pick the
> `revenue-collapse` scenario and press **Investigate** — the agent streams its
> work live. Then run the **same** incident a second time to see the
> organizational memory close the loop: the pattern is recognised before any
> work starts, the previously verified remediation is replayed, and the trust
> score rises.
>
> The API is public and can be exercised directly:
> `https://api.dataforensic.vylantic.com/api/v1/health`,
> `/api/v1/patterns`, `/api/v1/investigations/{id}`. `/api/v1/datahub/status`
> reports which MCP tools the agent resolved against the live server.
>
> The DataHub instance itself is browsable at
> `https://datahub.dataforensic.vylantic.com` — the fastest way to check the
> claim: search `sales_daily` and look at the `DataForensic:SCHEMA_DRIFT` tag
> and the institutional-memory link the agent wrote there.
>
> To run it locally instead: `cp .env.example .env && docker compose up -d`,
> then `./scripts/seed-demo.sh`. Full instructions in the README.
>
> The badge in the header states whether the context came from a live DataHub or
> from the deterministic graph shipped in the repository — it is never inferred,
> and the deployed instance is honest about which one it is using.

---

## 2. Project story

The Devpost "About the project" field asks for specific headings — inspiration,
what it does, how we built it, challenges, accomplishments, what we learned,
what's next. That text is written to those headings and ready to paste:
[`docs/devpost-story.md`](docs/devpost-story.md).

The material below predates that form and is kept as reference for the shorter
fields (tagline, testing instructions, technologies) and for the README.

## 2b. Project description — reference material

**paste — Devpost "About the project"**

### The problem

When a data metric breaks, the symptom is never where the cause is. Revenue
drops 18.5%, and someone now has to reconstruct, by hand and under pressure:
which dataset feeds that number, which pipeline writes it, what changed
upstream, what else consumes it, who owns those assets, and what a safe fix
looks like.

That reconstruction is repeated from scratch every single time — because the
reasoning ends up scattered across tickets, Slack threads and individual memory.
The context needed to do it already exists in DataHub. What has been missing is
an agent that reasons *through* it and gives the knowledge back.

### What it does

DATAFORENSIC AI takes an incident and runs the whole operational loop:

```
Incident → Context → Evidence → Root cause → Impact → Remediation → Verification
                                                                        ↓
                        future incidents start here  ←  Knowledge Pattern
```

It pulls asset context, schemas, lineage, ownership and quality signals from
DataHub; collects evidence with timestamps and provenance; generates and scores
competing hypotheses; names a probable root cause with a confidence breakdown;
computes the blast radius from real lineage; proposes and executes a safe
remediation in a controlled simulation; verifies the outcome; and writes the
finished investigation back into DataHub.

On the golden scenario it reaches `SCHEMA_DRIFT` at **92–97% confidence**, traces
the chain from an ERP field rename to a broken mapping to NULL discounts to a
corrupted revenue aggregate, walks the downstream lineage to **7–9 affected
assets across 3 owning teams**, and passes every verification check before the
incident is allowed to resolve.

The ranges are not hedging: the exact figures depend on what the catalog it is
pointed at actually contains. The reference run shipped in `examples/` scores 97
with 9 affected assets; the same investigation against a live DataHub scores 92
with 7, because two ML models there carry no lineage yet. Both are in the repo,
and the interface always reports which context source produced the number.

### What makes it different

**1. It is a memory engine, not a copilot.** Every resolved investigation is
folded into a *knowledge pattern* — the symptoms a failure mode shows up as, the
evidence signature that proves it, and the remediation that was actually
verified. The second time the same failure mode appears, the pattern is
recognised before any work starts and the verified plan is replayed instead of
regenerated.

Crucially, memory accelerates the investigation but **never replaces it**. A
recognised pattern arrives as a lead: the agent still walks lineage, still
collects its own evidence, still scores every alternative, and still has to
verify before anything resolves — so a pattern that does not actually fit simply
fails to be confirmed. There is a test named after exactly that invariant.

**2. Two numbers, not one.** Confidence says how strongly the evidence points at
this cause. The **Investigation Trust Score** answers a different and, for an AI
system, more important question: how much of this investigation was grounded in
retrieved context at all — evidence quality, schema validation, lineage
coverage, quality signals, historical precedent. The two are allowed to
disagree, and that is the point: an investigation can be 97% confident and
barely grounded, which is precisely what a thin context and a lucky correlation
look like from the inside. The trust score is computed without ever reading the
winning hypothesis' confidence, and a test proves it.

It earned its keep during development. The first version scored 75/100 with
schema validation only partial, because the agent named a field whose schema it
had never read. The fix was not to soften the check — it was to make the agent
read upstream schemas.

**3. Nothing is asserted that cannot be shown.** Five rules are enforced in the
code, not in a prompt:

- A hypothesis supported only by the reported symptom is never published as a
  root cause — the investigation blocks instead.
- Every tool call is logged and streamed; a tool that fails returns an explicit
  error rather than an empty list that reads like "nothing found".
- Risk is classified server-side; medium and high risk actions require explicit
  approval, and real production writes are refused even when the agent asks.
- `RESOLVED` is unreachable in the state machine except through a passing
  verification.
- An unverified fix never becomes the recommendation in the pattern library.

### How DataHub powers it

DataHub is not a data source rendered by the UI. It is the context layer the
agent reasons through. The agent reads:

- **asset context** — platform, domain, description, criticality, governance
- **schemas** — of the affected asset *and* of the upstream assets close enough
  to be implicated, so a field-level conclusion is never unverified
- **lineage** — upstream to find the cause, downstream to size the impact
- **ownership** — to know which teams have to act
- **quality context** — assertions and their run history
- **related assets** — domain, tag and glossary neighbours
- **change history** — the timeline that makes temporal correlation possible

…and writes back a complete investigation knowledge object: root cause,
evidence, **the hypotheses that were rejected**, blast radius, remediation,
verification, confidence and trust score — attached to the affected assets,
tagged with its pattern, and retrievable by the next investigation.

The integration goes through the **DataHub MCP Server** as the primary path
(`search`, `get_entities`, `list_schema_fields`, `get_lineage`), with GraphQL
and the Timeline API behind it for the two dimensions MCP does not expose at
all — the change timeline and assertion history. Temporal correlation depends
entirely on the former, so the second path is part of the design rather than a
safety net.

`/api/v1/datahub/status` reports which transport actually served the reads,
including a failed MCP handshake and its reason. Nothing in the interface claims
a path that was not used.

### How it works

A FastAPI backend hosts the agent; a Next.js frontend renders the investigation
as it happens over Server-Sent Events. Every event is persisted with a sequence
number *before* being published, so a client that reconnects replays from its
`Last-Event-ID` and the stream doubles as a complete action log.

The reasoning engine is deterministic and rule-based. Rules describe *shapes* of
signals, never scenarios — a schema change on a path to the target, an
unresolved column mapping, failed or late pipeline runs, quality anomalies on
graph source nodes. Confidence is a visible sum:

```
evidence strength + lineage relevance + temporal correlation
+ cross-signal agreement − contradicting evidence = 97 / 100
```

The reported symptom is deliberately excluded from cross-signal agreement — the
thing being explained cannot corroborate its own explanation — which is why the
golden scenario scores 97 and not 100.

An LLM is optional and strictly advisory (`LLM_PROVIDER=none` by default). When
configured, it may only propose *additional* candidate hypotheses that cite
evidence IDs the agent actually collected; proposals citing nothing are
discarded and the rejection is logged to the timeline.

### Proof that the reasoning is real

Three scenarios run through the **same generic engine** with no
scenario-specific code:

| Scenario | Signals present | Conclusion |
|---|---|---|
| `revenue-collapse` | schema change + broken mapping + content quality | `SCHEMA_DRIFT` 97% |
| `pipeline-freshness` | freshness breach + late run, **no schema change** | `FRESHNESS_STALENESS` 92% |
| `healthcare-quality` | quality anomaly on a source asset, **healthy mapping** | `SOURCE_DATA_ANOMALY` 86% |

Remove the schema-change evidence from the first scenario and `SCHEMA_DRIFT`
collapses on its own. There is a test for that too — and one named after a real
failure: seeding a live catalog writes schema changes dated today, which for a
while out-voted the correct conclusion on the healthcare scenario. Changes that
post-date the incident, and additive changes that cannot break a consumer, are
now excluded from causal reasoning.

### Technologies

Python 3.12, FastAPI, SQLAlchemy 2 (async), PostgreSQL, Server-Sent Events,
Next.js 16, React 19, TypeScript, Docker Compose. DataHub MCP Server, DataHub
GraphQL and Timeline APIs. No UI framework — the interface is hand-written CSS
built as a laboratory record rather than a dashboard.

### Data used

The demo context graph mirrors the structure of the official
`showcase-ecommerce`, `nyc-taxi` and `healthcare` datapacks, with identical URN
shapes, so the same investigation runs unchanged against a live DataHub loaded
with `datahub datapack load showcase-ecommerce`. No proprietary or personal data
is used anywhere.

### Open source contribution

The repository includes **`datahub/skills/incident-investigation/`**, a reusable
DataHub Skill that packages the non-opinionated half of an incident
investigation: gather asset context, trace lineage both ways, collect recent
changes, summarise downstream impact, and validate an investigation write-back
document.

It deliberately does *not* decide root causes and does *not* write to DataHub —
scoring stays with the agent, and performing the write stays with the caller so
the permission boundary stays where the caller controls it. It has no dependency
on DATAFORENSIC AI, runs against any client exposing the DataHub read surface,
and ships with 10 tests that run against an in-memory fake so it can be
validated without a DataHub instance.

**Upstream status: prepared, not yet submitted.** It is included in the
repository under Apache 2.0 and is ready to be adapted to the upstream skills
repository format.

Two smaller artefacts came out of running this against a real instance and may
be more immediately useful to the community than the Skill:
`datahub/mcp-bridge/`, which makes the stdio MCP server reachable over HTTP on
DataHub Core, and `docs/datahub-api-verification.md`, which records every
DataHub API claim this project makes with its source — including the ones that
turned out to be wrong. Neither has been submitted upstream, and neither is
claimed as a contribution.

### Running it against your own DataHub

The scenarios reference URNs shaped like the official datapacks but not
identical to them, so a DataHub that has never seen them answers with empty
entities — the investigation still runs on behavioural signals, but lineage and
blast radius come back empty and the trust score says so. One command fixes it:

```bash
python3 datahub/seed/emit_demo_graph.py      # --dry-run first if you like
```

The MCP server ships as a stdio process, so `datahub/mcp-bridge/` builds a small
image that exposes it over Streamable HTTP. Two findings from getting that
working are written down in `docs/datahub-api-verification.md`: the official
`mcp-server-datahub` cannot install on a musl base (its `google-re2` dependency
publishes manylinux wheels only), and a gateway answering an unknown session is
indistinguishable from a healthy empty reply.

### Testing

147 automated tests: state-machine invariants, the confidence formula, trust
score independence, blast-radius derivation, the DataHub provider contract, all
three scenarios end to end, the HTTP golden path with SSE resume, and the
failure modes — DataHub unavailable → `BLOCKED` with no invented cause;
verification `FAIL` → never `RESOLVED`; write-back failure → reported, not
hidden; high-risk action → refused without approval; an unverified fix → never
promoted into the pattern library.

### What's next

Recognising patterns across *related* assets rather than exact matches;
proposing DataHub assertions from resolved incidents so the next occurrence is
caught before a human notices; and an upstream PR for the Skill.

---

## 3. Judging criteria — where the evidence is

The criteria are five equally weighted, plus an open-source bonus. This maps
each one to something a judge can verify without taking our word for it.

| Criterion | Where to look |
|---|---|
| **Use of DataHub** | Seven context dimensions read per investigation, plus a validated write-back that creates a pattern tag, applies it to the affected assets and reads it back to confirm — visible in the DataHub UI, not just claimed. `examples/memory.json` shows the document. |
| **Technical execution** | 147 tests, including the failure modes. `examples/` contains real artefacts from an actual run, not hand-written samples. The whole loop runs from a clean clone with two commands. |
| **Originality** | The pattern library and the trust score. Neither is a DataHub feature rebuilt — both compose on top of the context graph and give something back to it. |
| **Real-world usefulness** | Incident investigation is a daily cost for data platform teams, and the reusable half of it — the reconstruction — is exactly what gets repeated. |
| **Submission quality** | README, `docs/architecture.md`, `docs/demo.md`, `docs/DEPLOY-DIGITALOCEAN.md`, `examples/`, and a video that shows the product, not slides. |
| **Open source bonus** | `datahub/skills/incident-investigation/` — independent, documented, tested. |

---

## 4. Pre-submission checklist

### Repository

- [ ] Public on GitHub
- [ ] `LICENSE` at the root, Apache 2.0, **detected by GitHub** — check the
      About sidebar actually reads "Apache-2.0 license", not "View license"
- [ ] README opens with what the project does, and the Quick start works from a
      clean clone on a machine that has never run it
- [ ] No secrets committed — `.env` is git-ignored, `.env.example` has no real
      values
- [ ] `examples/` present with the artefacts of a real run
- [ ] Everything in English

### Deployed instance

- [ ] Both domains respond over HTTPS with valid certificates
- [ ] `/api/v1/health` returns `status: ok`
- [ ] A full investigation has been run **on the deployed instance**, not only
      locally
- [ ] `python3 datahub/seed/emit_demo_graph.py` has been run, so lineage and
      blast radius are not empty
- [ ] `PUBLIC_APP_URL` points at the public domain — the link written into
      DataHub has to be clickable from someone else's browser
- [ ] `/api/v1/datahub/status` shows `mcp.ready: true` with a tool list
- [ ] The write-back status reads `VERIFIED`, not `WRITTEN UNVERIFIED`
- [ ] `datahub.<domain>` shows the `DataForensic:<pattern>` tag on the affected
      assets — the fastest proof of the write-back
- [ ] `/api/v1/patterns` already contains a verified pattern, so a judge's
      second run demonstrates the learning loop immediately
- [ ] The context-source badge matches what the description claims
- [ ] `ALLOW_REAL_REMEDIATION=false`, `/api/v1/demo/reset` returns 403
- [ ] **Calendar reminder: keep it running until August 31**

### Video

- [ ] Under 3 minutes
- [ ] Public on YouTube or Vimeo (not "unlisted" — the rules say publicly
      visible)
- [ ] Real product footage, no mockups, no fabricated results
- [ ] No copyrighted music, no third-party trademarks
- [ ] Audio intelligible, English
- [ ] DataHub usage visible on screen
- [ ] The second investigation is in the video — it is the differentiator
- [ ] The DataHub UI appears, showing the tag the agent wrote
- [ ] `/patterns` is empty before recording, so the library visibly grows

### Devpost form

- [ ] Project name, tagline, description
- [ ] Project URL, repository URL, video URL
- [ ] Category: Agents That Do Real Work
- [ ] Built-with tags
- [ ] Testing instructions with no credentials needed
- [ ] Open-source contribution declared **accurately** — the Skill is in the
      repository; do not claim an upstream PR that has not been opened
- [ ] Disclosure: the project was built during the submission period; AI coding
      assistants were used, which the rules explicitly permit

### Optional, worth the ten minutes

- [ ] Submit the Most Valuable Feedback survey — a separate $50 prize pool, one
      per individual, and it does not compete with the project submission
