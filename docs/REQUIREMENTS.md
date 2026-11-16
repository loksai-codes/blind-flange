# Blind Flange: Project Requirements

Status basis: 16 Nov 2026. Verified by a fresh `git clone`:
- Windows 11, Python 3.12, new virtual environment: `pip install -e .` and the
  README's check command gave BLOCK (exit 2).
- Current numbers, measured by `scripts/stats.py` and checked by a test: <!--stat:tests_passed-->266<!--/stat--> tests pass,
  `eval/compare.py` matches <!--stat:eval_matched-->35<!--/stat--> of <!--stat:eval_cases-->35<!--/stat--> cases, and <!--stat:mutations_caught_text-->12 of 12<!--/stat--> mutations are caught.
- GitHub Actions (`.github/workflows/ci.yml`) installs with `pip install .`, runs the tests and
  the eval on ubuntu-latest, macos-latest and windows-latest with Python 3.12, and fails if
  the committed stores or eval results change. All three passed (run 43852804742, 16 Nov).
- Ubuntu 24.04 under WSL2, Python 3.12.3: the check gave BLOCK (exit 2), and the tests and
  eval passed. That machine has no pip (and no sudo to
  install it), so the pinned dependency wheels were downloaded by pip on Windows
  and unpacked, with the package laid out as an install lays it out.

The first version of this file (audit of commit `3d84618`) listed 12 DONE,
16 PARTIAL and 12 MISSING. Section 14 records what changed.

## 1. Purpose and scope

Blind Flange is an offline tool that checks a proposed plant change against connected work permits and piping, shows the evidence path behind each modeled conflict, and withholds CLEAR when required information is missing.

It is decision support only. It does not authorize work, replace a permit system, or claim to prevent accidents. The plant data is illustrative and has not been reviewed by a process safety engineer.

## 2. Problem statement

Two work permits can each look safe on their own and still conflict, because the equipment they name is joined by piping that neither permit mentions. Matching permits by equipment tag misses this.

The Piper Alpha disaster (1988) is motivation only. This tool does not claim it would have prevented that disaster.

Given a proposed equipment change, the current valve states and every open permit, decide whether the change creates a modeled pressure connection to work or barriers that another permit relies on, and state how complete that decision is.

## 3. Users

- Permit coordinators and reviewers.
- Trainers and auditors replaying recorded scenarios.

## 4. High-level architecture

```text
Inputs: plant topology | valve observations (state, time, observer) | permits
                              |
        Import and validation (schema checks; unknown tags and ambiguous removals rejected)
                              |
        Relate store: one .rl file per shift (plant graph, permit layer, Store revision,
                      Evaluation records)
                              |
        Evaluator: src/blindflange/checks.py running queries/*.cypher, one process,
                   the only place a result is decided
                              |
        Interfaces: CLI | HTML/SVG evidence report | agent tools over MCP (assess_change, what_if)
```

- Agent tools may append Evaluation records. They cannot change plant state, permits or topology.
- No language model sits in the decision path.
- Every interface calls the same evaluator (`checks.evaluate`), so all give the same answer.

## 5. Data model

| Element | Meaning |
|---|---|
| `Component` | Pump, compressor, vessel, line, valve or blind. Properties: tag, kind, state, normal, pressure_source, integrity, observed_at, observed_by |
| `CONNECTED_TO` | Physical joint; walked in both directions |
| `Permit` | id, title, status (requested, active, closed). Status is authorization only |
| `WORKS_ON` | The permit opens the pipework at this component |
| `RELIES_ON` | The permit depends on this component as an isolation |
| `ENERGISES` | The permit starts or pressurises this equipment |
| `OPERATES {to}` | The permit needs this component changed to a new state |
| `Store` | One per file: revision, as_of, max_age_hours, eval_seq |
| `Evaluation` | Request, result, inputs snapshot (JSON), store revision, timestamp, kind |

Permit status (authorization) is kept separate from component observed state. Approving a permit records its state changes as `planned_state` / `planned_by` / `planned_at` and leaves the observed state alone; only an observation (`set --by`) verifies a state. See open question 7.

## 6. Functional requirements

| ID | Requirement | Acceptance criterion | Status | Evidence |
|---|---|---|---|---|
| FR-01 | Core graph: Component, CONNECTED_TO, Permit, WORKS_ON, RELIES_ON | Schema and store contain them | DONE | `schema/schema.cypher`; both committed stores |
| FR-02 | ENERGISES and OPERATES edges | Written when a permit is written | DONE | `queries/store.cypher` `permit_energises`, `permit_operates` |
| FR-03 | `Evaluation` node with inputs snapshot, result, revision, timestamp | Every check saves one | DONE | `test_every_evaluation_is_recorded_with_a_snapshot`, `test_check_changes_no_plant_state_or_permits_and_records_one_evaluation` |
| FR-04 | Component records `observed_at` and `observed_by` | Fields exist and are validated | DONE | `validate.plant`, `validate.scenario`, `validate.observation`; `tests/test_validate.py` |
| FR-05 | Pressure walk stops at barriers | Per-hop filter in a quantified path pattern | DONE | `queries/exposures.cypher`; `test_rule1_walk_stops_at_closed_valves_and_installed_blinds` |
| FR-06 | Before/after reachability comparison | Hazards caused by a change are identified | DONE | `checks.assess`; `hazards.introduced` |
| FR-07 | Existing, introduced and remaining hazards reported separately | `check` lists all three | DONE | `Result.hazards` (also `resolved`); `test_rule5_*` |
| FR-08 | Finding codes with verdicts | Each code produced and asserted by a test | DONE | Nine codes in `checks.SEVERITY`; each asserted by code in `tests/test_checks.py`, `tests/test_rules.py` |
| FR-09 | Starting or energising equipment is a new live pressure source on every path, including `set` | `set P-A in_service` is BLOCK | DONE | `test_starting_equipment_by_a_state_change_is_blocked`, `test_set_refuses_a_blocked_change_and_writes_nothing` |
| FR-10 | Two fields: `assessment_status` and `conflict_verdict` | Both returned by every interface | DONE | `checks.Result`; CLI text and `--json`; MCP `structuredContent`; `test_check_json_has_both_result_fields` |
| FR-11 | A component with no state is UNKNOWN, never a barrier; unknown or stale state yields INCOMPLETE when relevant | Test per rule 3 | DONE | `test_rule3_*` (four tests) |
| FR-12 | Removed component: one explicit representation; ambiguous removals rejected | Test for both cases | DONE | `removed` is an open end; `test_rule2_*` |
| FR-13 | Search bound detected | A truncated search is INCOMPLETE | DONE | `queries/bound.cypher`; `test_rule6_*` (three tests) |
| FR-14 | What-if command with hypothetical change and full re-check | Runs without changing plant state | DONE | `blindflange whatif`; `test_what_if_changes_nothing_but_appends_an_evaluation`, `test_whatif_changes_nothing` |
| FR-15 | Evidence path for every finding | Every finding has a valid path or a stated reason | DONE | One-hop findings carry graph edges as `evidence`; `test_every_finding_has_a_path_or_evidence` |
| FR-16 | Every evaluation recorded, including rejected requests; replay from snapshot | Reopened evaluation reproduces its result | DONE | `blindflange replay`; `test_rejected_requests_are_recorded_too`, `test_old_evaluation_reopened_after_the_plant_changed_still_reproduces`, `test_replay_detects_a_tampered_record` |
| FR-17 | Stale-revision rejection | A request against an old revision is refused | DONE | `store.write`; `approve/set --revision`; `test_stale_revision_is_refused_and_recorded` |
| FR-18 | All writes serialised through one application process | Concurrent writes cannot both commit | DONE | Relate file lock plus revision check inside the write transaction; `test_a_second_writer_is_refused`, `test_write_bumps_revision_and_rejects_stale_inside_the_transaction` |
| FR-19 | `check` and what-if do not alter topology, observations or permit authorization | Graph contents unchanged apart from a new Evaluation | DONE | Snapshot equality in `test_check_changes_no_plant_state_or_permits_and_records_one_evaluation` |
| FR-20 | Every input file validated with clear errors | Bad input gives a message, not a traceback | DONE | `src/blindflange/validate.py`; `test_bad_input_gives_one_line_errors_and_no_traceback` |
| FR-21 | HTML or SVG evidence view | Path, barriers and unknown states shown | DONE | `blindflange report`; `test_evaluations_replay_and_report` |
| FR-22 | Agent tools `assess_change` and `what_if` | Same result as the CLI | DONE | `blindflange mcp`; `tests/test_agent.py` including a stdio session |
| FR-23 | `reach` and `handover` commands | Run against a store | DONE | `reach --set` for what-if; `test_handover_lists_permits_and_hazards` |
| FR-24 | Evaluation suite with baselines and reported misses | Tag matching, independent oracle, list of misses | DONE | <!--stat:eval_cases-->35<!--/stat--> cases; `eval/oracle.py`; `## Misses` in `eval/results.md`; <!--stat:random_plants-->120<!--/stat--> random plants in `tests/test_oracle.py` |
| FR-25 | Plant: two or more sources, a bypass, a path of six or more hops | Verified by a test | DONE | `tests/test_gas_plant.py` (12-hop route through bypass BV-231) |
| FR-26 | `build` creates a store from a scenario | Store built and checkable | DONE | `tests/test_cli.py` fixture |
| FR-27 | `approve` and `close` commands | Approve stores a CLEAR or HOLD permit; close reports isolations still needed | DONE | `test_approve_stores_permit_applies_state_changes_and_bumps_revision`, `test_closing_a_permit_reports_isolations_still_needed` |
| FR-28 | `find` locates tags from free text | Full-text index query returns tags | DONE | `test_mcp_stdio_session` (find_tags) |
| FR-29 | Tag-matching baseline reported beside every permit verdict | Shown in CLI output and eval table | DONE | `queries/baseline.cypher`; asserted in `test_start_pump_a_is_blocked_with_a_path_and_no_shared_tag` |

## 7. Non-functional requirements

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| NFR-01 | Install and first result from a fresh clone in three commands | DONE | Fresh clone, `pip install -e .`, `python -m blindflange check ...`: BLOCK, exit 2 (Windows). The `blindflange` launcher can be blocked by Windows Application Control; README says so |
| NFR-02 | Clean errors, no tracebacks | DONE | `cli._run`; `test_bad_input_gives_one_line_errors_and_no_traceback` |
| NFR-03 | One pinned `relate-db` version | DONE | `relate-db==1.0.1` in `pyproject.toml` |
| NFR-04 | Runs on macOS and Linux | DONE | GitHub Actions run 43852804742 passed on macos-latest, ubuntu-latest and windows-latest (Python 3.12, `pip install .`, tests and eval); Ubuntu 24.04 under WSL2 checked by hand |
| NFR-05 | Inspectable committed `.rl` stores | DONE | `stores/condensate_unit.rl`, `stores/gas_plant.rl` |
| NFR-06 | Parameterised Cypher only, kept in `queries/` | DONE | All Cypher in `queries/`. The only text substitution is the validated integer hop bound, which Relate requires as a literal |
| NFR-07 | Schema validation of every input file and tool payload | DONE | `validate.py`; MCP tools publish `inputSchema` and validate through the same functions |
| NFR-08 | Reproducible store rebuild | DONE | Scenario `as_of` fixes every timestamp; `test_build_is_reproducible`; `eval/results.md` has no timings |
| NFR-09 | Tests prove what they claim | DONE | DEF-09 tests rewritten to assert codes, evidence and snapshots |
| NFR-10 | Documentation matches code | DONE | README, SPEC, RELATE_NOTES and this file updated together |
| NFR-11 | No language model in the decision path | DONE | Runtime dependencies: `relate-db`, PyYAML |

## 8. Result model and modeling rules

| `assessment_status` | Meaning |
|---|---|
| COMPLETE | All needed state is known and the search finished within its limits |
| INCOMPLETE | Required state unknown or stale, or the search hit a bound |
| ERROR | The input or the store is invalid, or the revision is stale |

| `conflict_verdict` | Meaning |
|---|---|
| BLOCK | A proven conflict introduced by the request, with an evidence path |
| HOLD | A proven condition requires review: a shared isolation, or an existing hazard the request does not remove |
| CLEAR | No specified conflict found. Valid only when COMPLETE |
| null | Incomplete with no proven conflict, or an error |

Each finding also carries `certainty`:

| `certainty` | Meaning |
|---|---|
| PROVEN | Every component the evidence path passes has a known, current state |
| POSSIBLE | The path passes at least one unknown or stale state |

- BLOCK can coexist with INCOMPLETE.
- A POSSIBLE finding never sets `conflict_verdict` on its own. It makes the assessment INCOMPLETE (severity UNCONFIRMED).
- BLOCK: pressure reaches open work; pressure reaches an untested temporary blind another permit relies on; pressure reaches an open end; own worksite not isolated; energising a worksite another permit is on; isolation removed; isolation not in place.
- HOLD: one isolation shared by two permits; two permits working on the same component (WORKSITE_SHARED); a proven existing hazard that the request leaves in place.

Modeling rules (each has at least one test in `tests/test_rules.py`):

1. Pressure passes a component unless it is closed or an installed blind (a barrier), or removed (an open end). The walk stops at the first such component.
2. A removed component is an open end: pressure reaches it and escapes, and reaching it is a finding. `removed` is rejected for a blind as ambiguous; a blind is `installed` or `not_installed`.
3. Unknown or stale state does not stop the walk. It makes the assessment INCOMPLETE when needed to establish or exclude a relevant source-to-target connection. Unrelated uncertainty is disclosed but does not hide a known conflict.
4. An untested temporary blind that pressure can reach is a BLOCK finding.
5. Existing, introduced and remaining hazards are reported separately. "Not newly caused" never means "no conflict".
6. If a search reaches its configured bound, the result is INCOMPLETE, never CLEAR.
7. Checks use the final state only. Multi-step procedures are unsupported.

Known simplification: reachability only. No flow direction, pressure level, fluid or non-return valves.

### Check flow

1. Resolve the tags and proposed states; reject unknown or ambiguous ones (ERROR, recorded).
2. Walk from every live pressure source in the current plant, in the PROVEN and POSSIBLE passes, and probe the bound.
3. Apply what-if changes, write the request and apply its changes, inside a transaction that is rolled back; walk again.
4. Compare, and report existing, introduced, remaining and resolved hazards separately.
5. Run the direct checks: energising a worksite, shared isolation, isolation removed, isolation not in place.
6. Attach an evidence path or edges to every finding and record what could not be established.
7. Save an `Evaluation` record.

A what-if repeats the check with a hypothetical change and always re-runs the whole check.

## 9. Verification plan

| Layer | Question | Status |
|---|---|---|
| Cypher against an independent traversal on randomized small topologies | Do both compute the same specified behaviour? | Done: <!--stat:random_plants-->120<!--/stat--> random plants, plus every eval case |
| Hand-written adversarial cases | Are the edge cases handled? | Done: <!--stat:eval_cases-->35<!--/stat--> eval cases and the rule tests |
| Practitioner review | Are the scenario, assumptions and wording plausible? | Not started |

Adversarial cases, all covered: worksite already exposed; second source added; removed inline component; barrier reached but not passed; unknown valve off and on a bypass; tied shortest paths; old evaluation reopened.

Cases are written before checks change, and misses are reported. They are author-written, not evidence of plant performance. Tied shortest paths must return the same finding and a valid path, not identical text.

## 10. Relate usage and limits

- Mode: single file, `stores/condensate_unit.rl` (and `stores/gas_plant.rl`). One shift hands the whole picture to the next as one file.
- One writing process per store. All writes go through `store.write`, which checks and bumps the revision in the same transaction.
- A `.rl` file can be opened again only after the connection holding it closes, read-only or not.
- Explicit hop bounds above 500 are refused (verified). Unbounded `+` is not limited (verified), so every walk here is bounded.
- Single-file mode needs the `.rl` suffix (verified).
- What-if checks do not change topology, observations or permit authorization, but they do append an Evaluation record. The file hash changes.
- An Evaluation stores a snapshot of its inputs, not only a revision number.

## 11. Out of scope

Electrical isolation, fluid properties, pressure levels, flow simulation, multi-step procedures, reading drawings from images, sign-in, automatic approval, vector search, minimal-cut remediation, general single-valve-boundary judgements.

## 12. Known defects

| ID | Defect (from the 16 Nov audit) | Status |
|---|---|---|
| DEF-01 | `set P-A in_service` returned CLEAR | Fixed: OPERATES to `in_service` on a pressure source makes it live; test |
| DEF-02 | A component with no state counted as isolating | Fixed: `coalesce(state, 'unknown')`; test |
| DEF-03 | `check` returned CLEAR while a standing hazard existed | Fixed: existing hazards give HOLD; test |
| DEF-04 | README said `check` "changes nothing" | Fixed: README says it appends an Evaluation |
| DEF-05 | Syntax error in `cli.py` | Fixed |
| DEF-06 | Scenario permits failed validation | Fixed |
| DEF-07 | `relate-db` not pinned | Fixed |
| DEF-08 | Store rebuild not reproducible | Fixed: scenario `as_of`; test |
| DEF-09 | Tests that did not assert what they claimed | Fixed |
| DEF-10 | `.gitignore` merged lines | Fixed |
| DEF-11 | Validation holes | Fixed; test |
| DEF-12 | Documentation drift | Fixed. The reserved id `__change__` carries a state change through the evaluator and is rejected as a permit id |
| DEF-13 | Cypher inline in Python | Fixed: `queries/store.cypher` |
| DEF-14 | Approval writes plant state | Fixed: approval writes `planned_state`, never an observation; `test_approval_records_planned_states_and_leaves_observations_alone` fails if it does |

## 13. Open questions

1. ~~Rename `source`.~~ Done: `pressure_source` and `observed_by`.
2. Staleness threshold: 12 hours (one shift) by default, set per scenario with `max_observation_age_hours`. A practitioner should confirm.
3. ~~Representation of a removed component.~~ Decided: open end; blinds cannot be removed.
4. `ENERGISES` and `OPERATES` edges persist for active permits, so `ISOLATION_REMOVED` and `ENERGISES_WORKSITE` can be found against them.
5. ~~Is `in_service` a valid `OPERATES {to}` for a pump?~~ Yes, and it makes the pump a live source.
6. `CLAUDE.md`, `SUBMISSION.md` and `docs/PLAN.md` are gitignored. Decide which should be public before submitting.
7. ~~Should `approve` apply the permit's planned state changes?~~ Decided (revised after the skeptical review): approval records them as planned, in separate fields, and never as observations. A planned state is unconfirmed, so it can give INCOMPLETE but never CLEAR. An operator's observation with `set --by` makes it verified. Tests: `tests/test_planned.py`.

## 14. Changes from the previous version

- All functional requirements are DONE. NFR-04 (macOS and Linux) is PARTIAL until re-run.
- Rule 1 states the `removed` open end explicitly; the first version's wording dropped it by mistake.
- HOLD now also covers a proven existing hazard that the request leaves in place.
- New finding code: PRESSURE_REACHES_OPEN_END.
- Added a second, larger illustrative plant (151 components) with a 12-hop headline route.

## Summary

| | DONE | PARTIAL | MISSING |
|---|---:|---:|---:|
| Functional (29) | 29 | 0 | 0 |
| Non-functional (11) | 11 | 0 | 0 |
| **Total (40)** | **40** | **0** | **0** |

Also done: the agent session for the M2 gate (`docs/agent-session.md`), the project page (`docs/index.html`), gallery images (`docs/media/`) and a sample evidence report (`docs/report-PTW-2201.html`).

What remains, and needs a person: make the repository public, record the demo video, and ask a practitioner to review the model (section 9).
