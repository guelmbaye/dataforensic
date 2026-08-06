# Video script — under 3 minutes

The rules are explicit: judges are not required to watch past three minutes, and
the footage must show the project actually working. So every second either shows
the product doing something or explains why what just happened matters. No title
cards, no architecture slides, no logo animation.

**Before recording:** `./scripts/reset-demo.sh`, then `./scripts/seed-demo.sh`.
Full pre-flight in `docs/demo.md`.

One decision to make before you press record: the header badge says whether the
context is a live DataHub or the deterministic graph. **Say out loud whatever
the badge says.** A demo on the fallback graph, described as such, is credible.
The same demo described as live is the one thing that cannot be repaired later.

---

## 0:00 – 0:15 · The problem

**Screen:** the incident queue. Revenue anomaly on `sales_daily`, observed
$10.1M against $12.4M expected.

> "Revenue is down 18.5%. Nobody knows why yet. Normally an engineer now spends
> an hour reconstructing context across five systems — which dataset feeds this
> number, what changed upstream, what else is affected."

## 0:15 – 0:45 · The agent goes to DataHub

**Screen:** press **Investigate**. Let the timeline stream. Do not skip it.

> "It asks DataHub for the context around the affected asset: schema, lineage
> both directions, ownership, quality signals, and what changed recently."

Point at the events as they land — `context_loaded`, `lineage_loaded`,
`schemas_inspected`, `changes_inspected`. The stream *is* the proof that work is
happening.

## 0:45 – 1:20 · Evidence, then a conclusion

**Screen:** evidence items appearing one at a time. Stop on two of them: the
schema change at 10:02, and the NULL rate going from 2.1% to 31.7% at 10:12.

> "Eleven signals, each with its source and its timestamp."

**Screen:** scroll to the hypotheses.

> "Four hypotheses, all scored. Pipeline failure is rejected — the runs actually
> succeeded, and successful runs *contradict* that hypothesis. Seasonality is
> rejected because there are hard technical signals. Schema drift is confirmed at
> 97%."

**Screen:** open the confidence breakdown.

> "And here is where that 97 comes from: evidence, lineage, timing,
> cross-signal agreement, minus contradictions. The number shows its work."

## 1:20 – 1:40 · Trust — the second number

**Screen:** the trust score panel, five checks visible.

> "A second, different number. Confidence says how strongly the evidence points
> here. Trust says how grounded this was at all — schema validated, lineage
> covered, quality signals present. They're allowed to disagree, and that's the
> point: 97% confident on a thin context is exactly what a hallucination looks
> like from the inside."

## 1:40 – 2:00 · Blast radius

**Screen:** the impact tab.

> "Nine assets, seven consumers, three owning teams — computed from the lineage
> DataHub returned, not from a lookup table. Two of them are ML models, which is
> why the risk comes out critical."

## 2:00 – 2:25 · Fix, then verify

**Screen:** press **Run simulation**, then the verification panel.

> "Five steps, low risk, executed in a controlled simulation — nothing in
> production is touched, and a riskier plan would be refused by the backend
> without an explicit approval."

> "Seven of seven checks pass: mapping restored, NULL rate normal, revenue
> recovered, downstream healthy. Only now does the incident become RESOLVED —
> the state machine makes it impossible to get there without a passing
> verification."

## 2:25 – 2:55 · The loop closes

**Screen:** create the **same** incident again. Do not narrate the mechanics —
let the recall banner and the timeline do it.

> "Same incident, second time. The pattern is recognised before any work starts.
> The remediation it applies is the one that was verified last time, not a new
> guess. And the trust score is now 100, because a confirmed precedent exists."

> "It still gathered its own evidence and still scored every alternative —
> memory makes it better, it doesn't let it skip the work."

**Screen:** the Memory page, pattern library.

## 2:55 – 3:00 · Close

> "DATAFORENSIC doesn't just find what broke. Every incident makes the next one
> cheaper, and the knowledge lives in DataHub instead of in someone's head."

---

## Recording notes

**Screen size.** Record at 1920×1080 and zoom the browser to 110–125%. The
interface uses monospace for measured values; at 100% on a 4K capture the URNs
are unreadable in a compressed YouTube stream, and the evidence is the whole
argument.

**Cut the dead air, keep the streaming.** Trimming a pause between two clicks is
fine. Speeding up the timeline is not — the progressive reveal is a feature
being demonstrated, and a sped-up stream reads as a fake one.

**If something fails mid-take, re-record.** Do not narrate over a broken run and
do not cut to a slide of what should have happened. If DataHub itself is
unreachable, the blocked state is worth showing on purpose: the agent refusing
to name a cause it cannot evidence is a feature, and there is a test for it.

**Audio.** No music. The rules prohibit copyrighted material and there is
nothing to gain — a plain voice track over a working product is the strongest
version of this video.

**Length.** Aim to land at 2:50. Going over three minutes does not disqualify
the entry, but everything after it is unwatched, and the second investigation —
the differentiator — is the last thing in the script.
