# Video script — under 3 minutes

The rules are explicit: judges are not required to watch past three minutes, and
the footage must show the project actually working. Every second here either
shows the product doing something or explains why what just happened matters. No
title cards, no architecture slides, no logo animation.

The story is the one the product is named after: **an incident is investigated,
proved, fixed, verified — and then it becomes knowledge that makes the next one
cheaper.** The second investigation is the point of the video, not an epilogue.
Everything before it is there to earn it.

---

## Before recording

```bash
./scripts/reset-demo.sh      # incidents, patterns, scenario worlds
./scripts/probe-mcp.sh       # optional: confirms the MCP bridge is answering
```

Then check three things on screen, because each one is a claim you are about to
make out loud:

| Check | Where | Expected |
|---|---|---|
| Context source | header badge | `Live DataHub` — or say "demo context graph" instead |
| MCP transport | `/api/v1/datahub/status` | `mcp.ready: true` with a tool list |
| Learning loop | `/patterns` | **empty** — the video has to start from nothing |

**Say whatever the badge says.** A demo running on the deterministic graph,
described as such, is credible. The same demo described as live is the one thing
that cannot be repaired afterwards.

Record at 1920×1080 with the browser zoomed to 110–125%. The interface uses
monospace for measured values; at 100% on a compressed YouTube stream the URNs
and the trust checks are unreadable, and those are the argument.

---

## 0:00 – 0:12 · The problem

**Screen:** the incident queue, one incident: revenue $10.1M against $12.4M.

> "Revenue is down 18.5%. Nobody knows why yet. Normally an engineer now spends
> an hour reconstructing context across five systems — which dataset feeds this
> number, what changed upstream, who owns what's affected."

## 0:12 – 0:40 · It goes to DataHub

**Screen:** press **Investigate**. Let the timeline stream. Do not skip it.

> "It asks DataHub for the context around the affected asset."

Point at the events as they land — `context loaded`, `lineage traced`,
`schemas inspected`, `changes inspected`. The stream *is* the proof that work is
happening, and it is live.

> "Lineage both directions, schemas of the asset and of everything close enough
> upstream to be implicated, ownership, quality signals, and the change
> timeline."

## 0:40 – 1:10 · Evidence first, then a conclusion

**Screen:** evidence items appearing one at a time. Stop on two: the unresolved
column mapping at 10:07, and the NULL rate going 2.1% → 31.7% at 10:12.

> "Every signal carries its source and its timestamp. Nothing here is the
> model's opinion."

**Screen:** scroll to the hypotheses.

> "Four hypotheses, all scored. Pipeline failure is rejected — the runs actually
> succeeded, and a successful run *contradicts* that hypothesis. Seasonality is
> rejected because there are hard technical signals. Schema drift is confirmed."

**Screen:** open the confidence breakdown.

> "And the number shows its work: evidence, lineage, timing, cross-signal
> agreement, minus contradictions."

## 1:10 – 1:28 · Trust — the second number

**Screen:** the trust score panel, five checks visible.

> "A second, different number. Confidence says how strongly the evidence points
> here. Trust says how grounded this was at all — schema validated, lineage
> covered, quality signals present, precedent or not. They're allowed to
> disagree, and that's the point: 97% confident on a thin context is exactly
> what a hallucination looks like from the inside."

Note the one check that is not full marks.

> "Historical match is zero. This is the first time this shape of incident has
> been seen. Remember that — it changes in ninety seconds."

## 1:28 – 1:45 · Blast radius

**Screen:** the Impact tab.

> "Affected assets, end consumers, owning teams — walked from the lineage
> DataHub returned, not from a lookup table. Dashboards and ML models included,
> which is why the risk lands where it does."

## 1:45 – 2:05 · Fix, then verify

**Screen:** press **Run simulation**, then the verification panel.

> "Five steps, low risk, executed in a controlled simulation. Nothing in
> production is touched — and a riskier plan would be refused by the backend
> without an explicit approval, however politely the agent asks."

> "Every check passes: mapping restored, NULL rate normal, revenue recovered,
> downstream healthy. Only now does the incident become RESOLVED — the state
> machine makes it impossible to get there any other way."

## 2:05 – 2:25 · The write-back, seen in DataHub

**Screen:** switch to the DataHub tab — the asset page, or Manage Tags.

This is the beat that turns a claim into evidence. Show the tag
`DataForensic: SCHEMA_DRIFT` applied to the affected assets.

> "And the investigation goes back into the catalog. This tag was written by the
> agent, on the assets it found. Anyone opening this dataset in DataHub tomorrow
> sees that it was involved in a schema-drift incident, and can follow the link
> to the full report."

## 2:25 – 2:50 · The loop closes

**Screen:** back to the incident queue, **Load and investigate** on the same
prepared scenario. Do not narrate the mechanics — let the recall banner and the
timeline do it.

> "Same failure mode, second time."

Point at the banner as it appears, then at the trust score.

> "The pattern is recognised before any work starts. The remediation it applies
> is the one that was verified last time, not a new guess. And historical match
> is no longer zero — the trust score is higher because a confirmed precedent
> now exists."

> "It still gathered its own evidence and still scored every alternative. Memory
> makes it better; it doesn't let it skip the work."

**Screen:** the **Memory** page.

> "That's the library. Every failure mode this organisation has actually lived
> through: the symptoms, the signals that prove it, and the fix that was
> verified."

## 2:50 – 3:00 · Close

> "DATAFORENSIC doesn't just find what broke. Every incident makes the next one
> cheaper — and the knowledge lives in DataHub, not in someone's head."

---

## What not to claim

The temptation is to say the second investigation is dramatically faster. **It
is not, and the video must not say so.** What is true and visible on screen:

- the pattern is matched before any evidence is gathered;
- the remediation is *reused* rather than generated — the panel says so;
- the trust score rises because the historical-match check now has something;
- the cost of both runs is measured and displayed, in DataHub calls and seconds.

That is a stronger claim than a stopwatch, and it survives a judge who reads the
numbers.

Two more things to avoid saying: that the agent "understands" the incident — it
scores evidence, which is more interesting and more defensible; and that the
remediation ran anywhere real — the panel says *controlled simulation*, and so
should you.

## Recording notes

**Cut dead air, never the stream.** Trimming a pause between two clicks is fine.
Speeding up the timeline is not: the progressive reveal is a feature being
demonstrated, and a sped-up stream reads as a fake one.

**No music.** The rules prohibit copyrighted material and there is nothing to
gain — a plain voice track over a working product is the strongest version of
this video.

**If something fails mid-take, re-record.** Do not narrate over a broken run and
do not cut to a slide of what should have happened. One exception is worth
keeping in your pocket: if DataHub is genuinely unreachable, the blocked state is
worth showing on purpose.

> "The investigation is blocked because the required context is unavailable. The
> agent will not name a cause it cannot evidence."

That is a demonstrable feature, there is a test for it, and it is a better
thirty seconds than a retake that hides it.

**Land at 2:50.** Going over three minutes does not disqualify the entry, but
everything after it is unwatched — and the second investigation, the thing that
makes this project different from a copilot, is the last beat.

## Shot list

| # | Time | Screen | Beat |
|---|---|---|---|
| 1 | 0:00 | Incident queue | The problem, in numbers |
| 2 | 0:12 | Workspace, timeline streaming | It queries DataHub, live |
| 3 | 0:40 | Evidence panel | Signals with sources and timestamps |
| 4 | 0:55 | Hypotheses + confidence breakdown | Alternatives scored, not skipped |
| 5 | 1:10 | Trust score panel | The second number, and the zero |
| 6 | 1:28 | Impact tab | Blast radius from real lineage |
| 7 | 1:45 | Resolution tab | Simulated fix, then verification |
| 8 | 2:05 | **DataHub UI** | The tag the agent wrote |
| 9 | 2:25 | Second run: recall banner | Pattern recognised, plan reused |
| 10 | 2:42 | Memory page | The library that grew |
| 11 | 2:50 | Memory page | Closing line |

## Publishing checklist

- [ ] Under 3 minutes
- [ ] Public on YouTube or Vimeo — public, not unlisted
- [ ] Real product footage, no mockups, no fabricated results
- [ ] No copyrighted music, no third-party trademarks
- [ ] Audio intelligible, English
- [ ] DataHub visible on screen, not just mentioned
- [ ] The second investigation is in the cut
- [ ] The narration matches the context-source badge
