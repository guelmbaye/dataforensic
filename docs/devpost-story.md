# Project story — paste into Devpost "About the project"

Written to the headings Devpost provides. Everything below is Markdown and can
be pasted as-is.

---

## Inspiration

When a data metric breaks, the symptom is never where the cause is.

Revenue drops 18.5%, and someone has to reconstruct, by hand and under pressure:
which dataset feeds that number, which pipeline writes it, what changed
upstream, what else consumes it, who owns those assets, and what a safe fix
looks like. We have all done that reconstruction. It takes an hour on a good
day.

What bothered us is that it gets repeated from scratch every single time. The
lineage, the schemas, the ownership, the change history — all of it already
exists in DataHub. The context is not missing. What is missing is anything that
reasons *through* it and gives the conclusion back.

So the resolution ends up in a ticket, the reasoning in a Slack thread, and the
next person facing the same failure mode starts from zero. We wanted to build
the thing that stops that from happening.

## What it does

DATAFORENSIC AI takes an incident and runs the whole operational loop a data
engineer would run by hand:

```
Incident → Context → Evidence → Root cause → Impact → Remediation → Verification
                                                                        ↓
                        future incidents start here  ←  Knowledge Pattern
```

It pulls asset context, schemas, lineage, ownership and quality signals from
DataHub; collects evidence with timestamps and provenance; generates and scores
competing hypotheses; names a probable root cause with a visible confidence
breakdown; computes the blast radius from real lineage; proposes and executes a
remediation in a controlled simulation; verifies the outcome; and writes the
finished investigation back into DataHub as a tag and a report the next
investigation can find.

On the golden scenario it reaches `SCHEMA_DRIFT` at 92–97% confidence, traces the
chain from an ERP field rename to a broken mapping to NULL discounts to a
corrupted revenue aggregate, walks the downstream lineage to 7–9 affected assets
across 3 owning teams, and passes every verification check before the incident is
allowed to resolve.

Two things make it more than an investigation tool.

**It exposes a second number.** Confidence says how strongly the evidence points
at this cause. The **Investigation Trust Score** answers a different question:
how much of this investigation was grounded in retrieved context at all —
evidence quality, schema validation, lineage coverage, quality signals,
historical precedent. The two are allowed to disagree, and that is the point. An
investigation can be 97% confident and barely grounded, which is exactly what a
thin context and a lucky correlation look like from the inside.

**It remembers.** Every resolved investigation is folded into a knowledge
pattern: the symptoms the failure mode shows up as, the evidence signature that
proves it, and the remediation that was actually verified. The second time the
same failure mode appears, the pattern is recognised before any work starts and
the verified plan is replayed instead of regenerated — while the agent still
gathers its own evidence and still scores every alternative.

## How we built it

A FastAPI backend hosts the agent; a Next.js frontend renders the investigation
as it happens over Server-Sent Events. PostgreSQL holds application state.
DataHub holds everything that matters about the data.

**The reasoning engine is deterministic and rule-based.** Rules describe *shapes*
of signals, never scenarios — a schema change on a path to the target, an
unresolved column mapping, failed or late pipeline runs, quality anomalies on
graph source nodes. Confidence is a visible sum:

$$\text{confidence} = E + L + T + X - C$$

where $E$ is evidence strength (max 30), $L$ lineage relevance (25), $T$ temporal
correlation (20), $X$ cross-signal agreement (25) and $C$ the penalty for
contradicting evidence. The reported symptom is deliberately excluded from $X$ —
the thing being explained cannot corroborate its own explanation — which is why
the golden scenario scores 97 and not 100.

An LLM is optional and strictly advisory (`LLM_PROVIDER=none` by default). When
configured, it may only propose *additional* candidate hypotheses that cite
evidence IDs the agent actually collected; proposals citing nothing are discarded
and the rejection is logged to the timeline.

**DataHub is reached through the MCP Server first** (`search`, `get_entities`,
`list_schema_fields`, `get_lineage`), with GraphQL and the Timeline API behind it
for the two dimensions MCP does not expose at all: the change timeline and
assertion history. Temporal correlation depends entirely on the former, so the
second path is part of the design rather than a safety net.

Five rules are enforced in the code rather than in a prompt: no root cause
without non-symptom evidence; no hidden actions; no silent tool failures; risk
classified server-side with real production writes refused by configuration; and
`RESOLVED` unreachable in the state machine except through a passing
verification.

147 automated tests cover the invariants, all three scenarios end to end, the
HTTP golden path with SSE resume, and the failure modes.

## Challenges we ran into

Almost every hard problem came from deploying it for real, and almost none of
them looked like what they were.

**The MCP server is a stdio process.** The Streamable HTTP endpoint documented by
DataHub is a Cloud feature; DataHub Core ships a stdio server meant for Claude
Desktop. We put a gateway in front of it — and then discovered that
`mcp-server-datahub` cannot install on a musl base at all, because its
`google-re2` dependency publishes manylinux wheels only. The failure was silent
in the worst way: the gateway started, answered its health endpoint, and only its
child process was dead. We now build a Debian-based bridge image with the server
installed at build time.

**A stale session is indistinguishable from a healthy reply.** After recreating
the bridge, our client kept presenting a session id the gateway no longer knew.
It was answered with HTTP 200 and an empty body — the exact shape a working
gateway uses when it replies on the stream — so the handshake timed out forever
while a fresh probe from the same container succeeded first try.

**The timeline was invisible in the browser while every server test passed.**
Each SSE frame carried `event: evidence_found`. `EventSource.onmessage` only
fires for *unnamed* frames, and there is no wildcard listener, so nothing ever
rendered. Our tests parsed `data:` lines directly and were perfectly green.

**Seeding a catalog became the cause.** Emitting the demo graph into a live
DataHub wrote schema changes dated today. Against a scenario dated months
earlier, those arrived as a dozen signals, out-voted the correct
`SOURCE_DATA_ANOMALY` on the healthcare scenario, and produced a root cause
naming a field that had merely been added. Two gates now stand between the
timeline and a causal claim: a change after the incident is dropped, and a change
must be able to break a consumer — a rename, a type change, a removal — to
support schema drift.

**Green tests that could not fail.** The suite ran at `LOG_LEVEL=CRITICAL`, so
`logger.info` returned before building a record and never triggered the
reserved-key collision that crashed production. The DataHub-unavailable tests
stubbed a provider that *returned* a failed result, while production *raised* —
so a real connection error ended an investigation as `FAILED` with a traceback
instead of `BLOCKED` with a reason. Both classes of test now exercise the path
they claim to.

## Accomplishments that we're proud of

**The trust score earns its keep.** Its first run scored 75/100 with schema
validation only partial, because the agent had named a field whose schema it
never read. We did not soften the check — we made the agent read upstream
schemas. A metric that finds a real weakness on its first day is worth keeping.

**Three scenarios, one engine, three conclusions.** `revenue-collapse` →
`SCHEMA_DRIFT`; `pipeline-freshness` → `FRESHNESS_STALENESS` with no schema
change anywhere; `healthcare-quality` → `SOURCE_DATA_ANOMALY` with a healthy
mapping. No scenario-specific code exists. Remove the schema-change evidence from
the first and `SCHEMA_DRIFT` collapses on its own — there is a test for exactly
that.

**Nothing is claimed that is not reported.** The context-source badge renders
what the API reports, never an inference; a failed MCP handshake is visible with
its reason; a write-back that DataHub refuses is reported as such, and the
pattern is still learned locally so the learning loop does not depend on one
token having tag-write permission.

**Verification is structural, not aspirational.** `RESOLVED` cannot be reached
except through a passing verification, because the state machine has no edge to
it from anywhere else.

## What we learned

That the distance between "the API answers" and "the thing works" is where all
the time goes. GMS returned 200 while its search backend was unreachable. The
bridge returned `ok` on `/healthz` with a dead process behind it. A status
endpoint reported a startup snapshot long after the world had changed. Each one
looked healthy from exactly the angle we were checking.

That a test only protects the path it exercises. Ours were green through a
production crash, a browser-invisible timeline, and an unwrapped transport error.

And that verifying claims is cheaper than repairing them. Halfway through we
audited every DataHub-specific assertion in the repository against the official
documentation and found several we had invented — tool names, Timeline API
parameter names, container names, an image that does not exist. That audit lives
in the repo as `docs/datahub-api-verification.md`, recording what is verified,
what is not, and how the code degrades when the unverified parts are wrong.

## What's next for DATAFORENSIC AI

**Recognising patterns across related assets**, not just exact matches — a
failure mode that hit `orders_enriched` should be recognisable when it hits its
sibling.

**Proposing DataHub assertions from resolved incidents.** Every investigation
ends knowing which measurement would have caught the problem earlier. Writing
that back as an assertion turns the memory from a lookup into prevention.

**Contributing upstream.** The repository already contains a reusable DataHub
Skill for the non-opinionated half of an incident investigation, and an MCP
bridge that makes the stdio server reachable over HTTP on DataHub Core. Neither
has been submitted upstream yet, and neither is claimed as a contribution — but
the bridge in particular solves a problem anyone self-hosting will hit.
