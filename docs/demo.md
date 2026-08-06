# Demo runbook

Target: under three minutes, reproducible from a clean environment, with nothing
on screen that the product does not actually do.

## Before every run

```bash
./scripts/reset-demo.sh     # resets app state, scenario state and incident memory
./scripts/seed-demo.sh      # validates lineage, creates the demo incident
```

The reset script prints the pre-demo checklist and refuses to pass if the API,
the database or the context source is not healthy. It also prints which context
source is active — check that the badge in the UI matches what you are about to
say out loud.

Rehearse three times: once normally, once with artificial latency, once without
looking at the logs. The demo has to behave like a product, not like a debugging
session.

## The three-minute script

**0:00 – 0:20 — the problem**

Show the incident. Revenue is $10.1M instead of $12.4M.

> "Our revenue metric is wrong. We don't know why. Normally an engineer now
> spends an hour reconstructing context across five systems."

**0:20 – 0:50 — the agent starts**

Press **Investigate**. Let the timeline stream — do not skip it. The events are
the proof that work is happening: context loaded, lineage traced, changes
inspected.

> "It's asking DataHub for the context around the affected asset: schema,
> lineage both ways, ownership, quality signals, and what changed recently."

**0:50 – 1:30 — the investigation**

Evidence appears one item at a time. Point at the two that matter: the schema
change at 10:02, and the NULL rate jumping from 2.1% to 31.7% at 10:12.

Then the hypotheses — and this is the moment that separates this from a chatbot:

> "Four hypotheses, all scored. Pipeline failure is rejected — the runs actually
> succeeded, and successful runs *contradict* that hypothesis. Seasonality is
> rejected because there are hard technical signals. Schema drift is confirmed
> at 97%, and here is the breakdown of that number."

Open the score breakdown. 30 + 25 + 20 + 22.

**1:30 – 1:55 — blast radius**

> "Nine assets, seven consumers, three owning teams — computed from the lineage
> DataHub returned, not from a lookup table. Two of them are ML models, which is
> why the risk is critical rather than high."

**1:55 – 2:25 — remediation**

Press **Execute simulation**.

> "Five steps, classified low risk, executed in a controlled simulation. Nothing
> in production is touched — and if the plan were higher risk, the backend would
> refuse to run it without an explicit approval, even if the agent asked."

**2:25 – 2:45 — verification**

> "Seven of seven checks pass: mapping restored, NULL rate normalised, revenue
> recovered, downstream assets healthy. Only now does the incident become
> RESOLVED — the state machine makes it literally impossible to get there
> without a passing verification."

**2:30 – 2:45 — trust**

Open the trust score next to the confidence number.

> "Two different numbers. Confidence says how strongly the evidence points here.
> Trust says how much of this was grounded in retrieved context at all — evidence
> quality, schema validation, lineage coverage, quality signals, precedent. They
> can disagree, and that is the point: a 97% conclusion on a thin context is
> exactly what a hallucination looks like from the inside."

**2:45 – 3:00 — the loop closes**

Create the same incident a second time. Do not narrate the mechanics; let the
screen do it.

> "The pattern is recognised before any work starts. The remediation it applies
> is the one that was verified last time, not a new guess. And the trust score is
> now 100, because a confirmed precedent exists. It still gathered its own
> evidence and still scored every alternative — memory makes it better, it does
> not let it skip the work."

Finish on the Memory screen.

> "That is the product. Not an agent that answers questions about data — a system
> where every incident makes the next one cheaper, and the knowledge lives in
> DataHub rather than in someone's head."

**Closing line**

> "DATAFORENSIC doesn't just find what broke. It turns every incident into
> reusable organisational knowledge."

## What to do when something fails live

1. Retry once.
2. If it recovers, keep going.
3. If it does not, switch to the controlled fallback — and say so.
4. Never fabricate a result.

If DataHub is genuinely unreachable, the honest line is the strong one:

> "The investigation is blocked because the required context source is
> unavailable — which is exactly what should happen. The agent will not invent a
> root cause it cannot evidence."

That is a demonstrable feature, and there is a test for it.

## Secondary scenarios

Worth showing if there is time or if a judge asks whether the reasoning is real:

```bash
# no schema change anywhere → FRESHNESS_STALENESS
curl -X POST localhost:8000/api/v1/incidents -H 'Content-Type: application/json' \
  -d @scenarios/pipeline-freshness/incident.json

# healthy mapping, bad source batch → SOURCE_DATA_ANOMALY
curl -X POST localhost:8000/api/v1/incidents -H 'Content-Type: application/json' \
  -d @scenarios/healthcare-quality/incident.json
```

Same engine, same code path, three different conclusions.

## Recording

The shot-by-shot script, with timings and narration, is in
[`video-script.md`](video-script.md). The checklist below is what to verify
before publishing.

## Recording checklist

- [ ] under 3 minutes
- [ ] public visibility
- [ ] actual product footage, no mockups
- [ ] no fabricated result
- [ ] no copyrighted music or third-party material
- [ ] audio understandable
- [ ] DataHub usage visible on screen
- [ ] the full loop visible end to end
- [ ] the context-source badge matches what is claimed in the narration
