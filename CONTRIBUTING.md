# Contributing

## Local setup

```bash
cp .env.example .env
cd apps/api && pip install -e ".[dev]"
pytest
```

Tests run against SQLite and the deterministic context graph, so no Docker and
no DataHub instance are required to work on the agent.

## Running one scenario without HTTP

```bash
cd apps/api
DATAHUB_MODE=fixture python3 -m app.cli.run_scenario revenue-collapse
```

Prints the full timeline, evidence, hypotheses with score breakdowns, blast
radius, verification checks and the write-back reference.

## House rules

**Never encode a scenario into the engine.** If a change makes a specific
incident work but would not generalise, it belongs in a scenario file, not in
`agents/`. The test `test_the_three_scenarios_do_not_share_a_conclusion` exists
to catch this.

**Evidence before inference.** Anything the agent asserts must be traceable to
an `EvidenceItem` with a source. Adding a conclusion path that bypasses evidence
will fail `test_the_root_cause_is_backed_by_non_symptom_evidence`.

**Failures must be visible.** A tool that cannot answer returns an explicit
failed `ToolResult`. Returning `[]`, `None` or `{}` on error is not acceptable:
downstream that reads as "nothing found", which is a different and much more
dangerous statement.

**Never let the fallback impersonate DataHub.** Any new provider method must set
`source`, `source_system` and `source_mode` correctly.

**Guardrails belong server-side.** Enforcement lives in `domain/` and is called
by the API. Anything enforced only in the agent, or only in the UI, is not
enforced.

## Adding a scenario

1. Create `scenarios/<id>/scenario.json` with the world states (`BROKEN`,
   `REMEDIATED`), the remediation template and the verification checks.
2. Add `incident.json` — **without the cause in it**.
3. Add `expected.json` with the test truth.
4. Add the entities and lineage to `datahub/seed/build_graph.py`, then
   `python3 datahub/seed/build_graph.py`.
5. Add the scenario id to `SCENARIOS` in `tests/test_agent_investigation.py`.

If the engine needs new code to solve your scenario, the new code must be a
generic signal shape, and the existing scenarios must still pass unchanged.

## Brand assets

`brand/logo-master.png` is the source. Never edit a derived file by hand — the
favicon, the app icons and both lockups are produced by
`python3 scripts/build-brand-assets.py` (requires Pillow). Editing a generated
asset means the next run silently reverts it.

## Style

Ruff for Python. Comments explain *why*, not *what*. Keep abstractions that have
a single implementation simple.
