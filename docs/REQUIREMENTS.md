# Blind Flange: Project Requirements

Status basis: commit `3d84618` (HEAD), audited on 16 Nov 2026 by installing a
`git archive` export of HEAD into a fresh virtual environment and running it with
`python -m blindflange`. The uncommitted working tree on `step-2-robustness` is
broken and is not used for any status below (see DEF-05 and DEF-06).

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
Inputs: plant topology | valve observations (state, time, source) | permits
                              |
        Import and validation (schema checks; unknown tags and ambiguous removals rejected)
                              |
        Relate store: one .rl file per shift (plant graph, permit layer, Evaluation records)
                              |
        Evaluator: reviewed, parameterised Cypher, one application process,
                   the only place a result is decided
                              |
        Interfaces: CLI | HTML/SVG evidence view | agent tools (assess_change, what_if)
```

- Agent tools may append Evaluation records. They cannot change plant state, permits or topology.
- No language model sits in the decision path.
- Every interface calls the same evaluator, so all give the same answer.

## 5. Data model

| Element | Meaning |
|---|---|
| `Component` | Pump, vessel, line, valve or blind. Properties: tag, kind, state, observed_at, source (see open question 1) |
| `CONNECTED_TO` | Physical joint; walked in both directions |
| `Permit` | id, title, status (requested, active, closed). Status is authorization only |
| `WORKS_ON` | The permit opens the pipework at this component |
| `RELIES_ON` | The permit depends on this component as an isolation |
| `ENERGISES` | The permit starts or pressurises this equipment |
| `OPERATES {to}` | The permit needs this component changed to a new state |
| `Evaluation` | Inputs snapshot, result, store revision, timestamp |

Permit status (authorization) is kept separate from component observed state. HEAD does not yet do this (DEF-14).

## 6. Functional requirements

| ID | Requirement | Acceptance criterion | Status | Evidence |
|---|---|---|---|---|
| FR-01 | Core graph: Component, CONNECTED_TO, Permit, WORKS_ON, RELIES_ON | Schema and store contain them | DONE | `schema/schema.cypher`; store has 35 / 37 / 2 / 2 / 3 |
| FR-02 | ENERGISES and OPERATES edges | Written when a permit is written | DONE | `store.write_permit`; none in the committed store |
| FR-03 | `Evaluation` node with inputs snapshot, result, revision, timestamp | Every check saves one | MISSING | 0 nodes; not in any file |
| FR-04 | Component records `observed_at` and `source` | Fields exist and are validated | MISSING | Neither field exists |
| FR-05 | Pressure walk stops at closed or installed components | Per-hop filter in a quantified path pattern | DONE | `queries/exposures.cypher`, `queries/reach.cypher`. HEAD also stops at `removed`; see rule 1 and FR-12 |
| FR-06 | Before/after reachability comparison | Hazards caused by a change are identified | DONE | `checks.findings_for` |
| FR-07 | Existing, introduced and remaining hazards reported separately | `check` lists all three | PARTIAL | Only introduced hazards in `check` |
| FR-08 | Seven finding codes with verdicts | Each code produced and asserted by a test | PARTIAL | `checks.SEVERITY`; ENERGISES_WORKSITE is asserted only through a verdict (eval case 10), which ISOLATION_REMOVED alone would satisfy |
| FR-09 | Starting or energising equipment is a new live pressure source on every path, including `set` | `set P-A in_service` is BLOCK | MISSING | DEF-01 |
| FR-10 | Two fields: `assessment_status` and `conflict_verdict` | Both returned by every interface | MISSING | Only `verdict` exists |
| FR-11 | A component with no state is UNKNOWN, never a barrier; unknown or stale state yields INCOMPLETE when relevant | Test per rule 3 | MISSING | DEF-02 |
| FR-12 | Removed component: one explicit representation; ambiguous removals rejected | Test for both cases | PARTIAL | `removed` stops the walk; reported only with WORKS_ON |
| FR-13 | Search bound detected | A truncated search is INCOMPLETE | MISSING | Unbounded `+` with no flag |
| FR-14 | What-if command with hypothetical change and full re-check | Runs without changing plant state | PARTIAL | `$assume_*` parameters inside `check` only |
| FR-15 | Evidence path for every finding | Every finding has a valid path or a stated reason | PARTIAL | One-hop findings from `direct.cypher` have no path |
| FR-16 | Every evaluation recorded, including rejected requests; replay from snapshot | Reopened evaluation reproduces its result | MISSING | Nothing found |
| FR-17 | Stale-revision rejection | A request against an old revision is refused | MISSING | No revision property |
| FR-18 | All writes serialised through one application process | Concurrent writes cannot both commit | PARTIAL | Relate file lock only |
| FR-19 | `check` and what-if do not alter topology, observations or permit authorization | Graph contents unchanged apart from a new Evaluation | DONE | HEAD `check` on a store copy: all 45 node and edge rows identical before and after. File bytes change (DEF-04), which section 10 allows |
| FR-20 | Every input file validated with clear errors | Bad input gives a message, not a traceback | PARTIAL | HEAD probes in DEF-11 |
| FR-21 | HTML or SVG evidence view | Path, barriers and unknown states shown | MISSING | Not started |
| FR-22 | Agent tools `assess_change` and `what_if` | Same result as the CLI | MISSING | Not started |
| FR-23 | `reach` and `handover` commands | Run against a store | DONE | Both ran against a copy of the committed store. `reach` takes no what-if assumptions; that is covered by FR-14 |
| FR-24 | Evaluation suite with baselines and reported misses | Tag matching, independent oracle, list of misses | PARTIAL | 10 cases; tag matching only; no oracle |
| FR-25 | Plant: two or more sources, a bypass, a path of six or more hops | Verified by a test | PARTIAL | 35 components; 5 sources; bypasses exist; longest path 4 hops; no test |
| FR-26 | `build` creates a store from a scenario | Store built and checkable | DONE | `test_cli_runs_as_a_python_module` |
| FR-27 | `approve` and `close` commands | Approve stores a non-blocked permit; close reports isolations still needed | DONE | `test_approve_stores_permit_and_applies_state_changes`, `test_blocked_permit_is_not_stored_on_approve`, `test_closing_a_permit_reports_isolations_still_needed`. Meaning of approval: open question 7 |
| FR-28 | `find` locates tags from free text | Full-text index query returns tags | DONE | `find "relief valve pump A"` returned P-A, SV-A, DV-A, DR-A, PSV-504. No test |
| FR-29 | Tag-matching baseline reported beside every verdict | Shown in CLI output and eval table | DONE | `checks.baseline`; asserted in `test_start_pump_a_is_blocked_with_a_path_and_no_shared_tag` |

## 7. Non-functional requirements

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| NFR-01 | Install and first result from a fresh clone in three commands | PARTIAL | HEAD export, non-editable install, `python -m blindflange`: 19 tests pass, BLOCK returned. Not yet run as the README states it (clone, `pip install -e .`, `blindflange` launcher). The launcher was blocked by Windows Application Control |
| NFR-02 | Clean errors, no tracebacks | PARTIAL | HEAD gives a raw TypeError on a YAML list |
| NFR-03 | One pinned `relate-db` version | MISSING | `>=1.0.1` |
| NFR-04 | Runs on macOS and Linux | PARTIAL | Windows verified in this audit. Linux verified by the author with Python 3.13 per `docs/RELATE_NOTES.md`, not re-audited. macOS unverified |
| NFR-05 | Inspectable committed `.rl` store | DONE | `stores/condensate_unit.rl` |
| NFR-06 | Parameterised Cypher only, kept in `queries/` | PARTIAL | Values are parameters. Label and relationship type are built with f-strings at `store.py:109` and `store.py:163-164`, from fixed dictionaries. About 23 Cypher strings are inline in Python (DEF-13) |
| NFR-07 | Schema validation of every input file and tool payload | PARTIAL | HEAD rejects unknown tags and invalid plant states only. `validate.py` exists only in the uncommitted working tree and is unverified |
| NFR-08 | Reproducible store rebuild | MISSING | Scenario has no `as_of` (DEF-08) |
| NFR-09 | Tests prove what they claim | PARTIAL | DEF-09 |
| NFR-10 | Documentation matches code | PARTIAL | DEF-04, DEF-12 |
| NFR-11 | No language model in the decision path | DONE | Runtime dependencies: `relate-db`, PyYAML |

## 8. Result model and modeling rules

| `assessment_status` | Meaning |
|---|---|
| COMPLETE | All needed state is known and the search finished within its limits |
| INCOMPLETE | Required state unknown or stale, unknown tag, unsupported component, or the search hit a bound |
| ERROR | The input or the store is invalid |

| `conflict_verdict` | Meaning |
|---|---|
| BLOCK | A modeled conflict exists, with an evidence path |
| HOLD | A modeled dependency or condition requires review |
| CLEAR | No specified conflict found. Valid only when COMPLETE |
| null | Incomplete with no established conflict, or an error |

Each finding also carries `certainty`:

| `certainty` | Meaning |
|---|---|
| PROVEN | Every component on the evidence path has a known, current state |
| POSSIBLE | The path passes through at least one unknown or stale state |

- BLOCK can coexist with INCOMPLETE.
- A POSSIBLE finding never sets `conflict_verdict` to BLOCK on its own. It makes the assessment INCOMPLETE.
- BLOCK: pressure reaches open work; pressure reaches an untested temporary blind another permit relies on; own worksite not isolated; energising a worksite another permit is on; isolation removed; isolation not in place.
- HOLD: one isolation shared by two permits.

Modeling rules (each needs at least one test):

1. Pressure passes a component unless it is closed or an installed blind. The walk stops at the first such component. This changes the current rule, which also stops at `removed` (see section 14). Change `queries/exposures.cypher`, `queries/reach.cypher` and `docs/SPEC.md` together.
2. A removed component is supported through one explicit representation. Ambiguous removals are rejected.
3. Unknown or stale state does not stop the walk. It makes the assessment INCOMPLETE when needed to establish or exclude a relevant source-to-target connection. Unrelated uncertainty is disclosed but does not hide a known conflict.
4. An untested temporary blind that pressure can reach is a BLOCK finding.
5. Existing, introduced and remaining hazards are reported separately. "Not newly caused" never means "no conflict".
6. If a search reaches its configured bound, the result is INCOMPLETE, never CLEAR.
7. Checks use the final state only. Multi-step procedures are unsupported.

Known simplification: reachability only. No flow direction, pressure level, fluid or non-return valves.

### Check flow

1. Resolve the tag and proposed state; reject unknown or ambiguous ones.
2. Walk from every live pressure source in the current plant.
3. Walk again with the proposed changes applied, inside a transaction that is rolled back.
4. Compare, and report existing, introduced and remaining hazards separately.
5. Run the direct checks: energising a worksite, shared isolation, isolation removed, isolation not in place.
6. Attach an evidence path to every finding and record what could not be established.
7. Save an `Evaluation` record.

A what-if repeats the check with a hypothetical change and always re-runs the whole check.

## 9. Verification plan

| Layer | Question |
|---|---|
| Cypher against an independent traversal on randomized small topologies | Do both compute the same specified behaviour? |
| Hand-written adversarial cases | Are the edge cases handled? |
| Practitioner review | Are the scenario, assumptions and wording plausible? |

Adversarial cases: worksite already exposed; second source added; removed inline component; barrier reached but not passed; unknown valve off and on a bypass; tied shortest paths; old evaluation reopened.

Cases are written before checks change, and misses are reported. They are author-written, not evidence of plant performance. Tied shortest paths must return the same finding and a valid path, not identical text.

## 10. Relate usage and limits

- Mode: single file, `stores/condensate_unit.rl`. One shift hands the whole picture to the next as one file.
- One writing process per store. Serialise all writes and reject requests against a stale revision.
- A `.rl` file opens read-only beside a writer only after the writer exits.
- Explicit hop bounds above 500 are rejected unless raised. Unverified: not in `docs/RELATE_NOTES.md` and not tested. Test it before FR-13 relies on it.
- Traversal behaviour may depend on query form and version (unverified). Pin one version and test the exact queries at, below and beyond their bounds.
- What-if checks do not change topology, observations or permit authorization, but they do append an Evaluation record. Do not claim the file hash is unchanged.
- An Evaluation stores a snapshot of its inputs, not only a revision number.

## 11. Out of scope

Electrical isolation, fluid properties, pressure levels, flow simulation, multi-step procedures, reading drawings from images, sign-in, automatic approval, vector search, minimal-cut remediation, general single-valve-boundary judgements.

## 12. Known defects

| ID | Severity | Defect | Evidence | Violates |
|---|---|---|---|---|
| DEF-01 | High | `set P-A in_service` returns CLEAR and commits; the Piper Alpha-type hazard then exists | `whatif.cypher` ignores starting equipment | FR-09 |
| DEF-02 | High, untested | A component with no state counts as isolating (`NOT null IN [...]` is null) | Code reading | FR-11 |
| DEF-03 | High | `check` returns CLEAR while a standing hazard exists | Probe: EV-1 open, then check PTW-0850 | FR-07 |
| DEF-04 | Low | README says `check` "Changes nothing"; the file bytes do change, though graph contents do not | Hash 3eeed27d to a58cf8df; contents identical | NFR-10 |
| DEF-05 | Blocker (working tree) | Syntax error in `cli.py:196` | Python SyntaxError; causes the 1 test failure | NFR-01 |
| DEF-06 | Blocker (working tree) | `store.py:265` calls `validate.permit` without `in_scenario=True`, so `build` rejects scenario permits | Causes 16 test errors | NFR-01 |
| DEF-07 | Medium | `relate-db` not pinned | `pyproject.toml` | NFR-03 |
| DEF-08 | Medium | Store rebuild writes a new `approved_at` and a new binary each time | No `as_of` in scenario | NFR-08 |
| DEF-09 | Medium | Three tests and one eval case do not assert what their names claim | `test_check_is_a_dry_run` (permit ids only, in memory), `test_unlisted_route_into_open_work_is_found` (path, not code), `test_no_standing_hazards_at_start_of_shift` (passes if the query returns nothing), eval case 10 (passes on ISOLATION_REMOVED alone) | NFR-09 |
| DEF-10 | Low | `.gitignore` merged two lines; `.claude/settings.local.json` no longer ignored and `build/` shows as untracked | `.claude/build/` | NFR-10 |
| DEF-11 | Medium | HEAD validation holes: string `works_on`; `to: sideways` gives CLEAR; YAML list gives a raw TypeError; a missing `--store` creates an empty file | HEAD probes | FR-20 |
| DEF-12 | Low | Documentation drift: 16 vs 19 tests; schema comment vs `model.py` states; undocumented `validate` command; hard-coded "35-component plant"; `<REPO_URL>` placeholder; `__state_change__` sentinel | Audit | NFR-10 |
| DEF-13 | Low | About 23 Cypher strings are inline in Python, against the CLAUDE.md rule "Keep Cypher in `queries/`" | 17 in `store.py`, 5 in `cli.py`, 1 in `checks.py` | NFR-06 |
| DEF-14 | Medium | Approval writes plant state: `store.activate` applies OPERATES states and sets energised equipment to `in_service` | `store.activate` | Section 5 |

## 13. Open questions

1. The schema field `source` means "pressure source" (boolean). The new observation `source` means "who observed it". Rename one. Suggested: `is_pressure_source` and `observed_by`.
2. How old must an observation be to count as stale? A threshold is needed.
3. Which single representation of a removed component is supported?
4. Should `ENERGISES` and `OPERATES` edges persist in the store, or exist only during a check?
5. Is `in_service` a valid `OPERATES {to}` value for a pump? The checker must treat it as a new live source.
6. `CLAUDE.md`, `SUBMISSION.md` and `docs/PLAN.md` are gitignored and have never been committed. Decide which should be public. `SUBMISSION.md` is meant to stay in step with the README but is not tracked in git.
7. What does `approve` mean, given that the tool "does not authorize work" and automatic approval is out of scope? Options: rename it to record a coordinator's decision, or remove it.

## 14. Changes from previous version

New file. Where it conflicts with `docs/SPEC.md`, `docs/PLAN.md` or `README.md`, this file wins.

- Added: `assessment_status` and `conflict_verdict`, finding `certainty`, UNKNOWN state handling, search bounds, Evaluation records with snapshot, stale-revision rejection, and agent tools.
- Changed: HOLD now means "requires review". A what-if may append an Evaluation record. Passability: `removed` no longer stops the walk by itself (rule 1); removals follow rule 2.
- Dropped: vector search, minimal-cut remediation, and single-valve-boundary judgements.

## Summary

| | DONE | PARTIAL | MISSING |
|---|---:|---:|---:|
| Functional (29) | 10 | 9 | 10 |
| Non-functional (11) | 2 | 7 | 2 |
| **Total (40)** | **12** | **16** | **12** |

Five biggest gaps:

1. The working tree does not run (DEF-05, DEF-06).
2. Starting equipment through `set` is not checked (DEF-01).
3. No incomplete-assessment model: no `assessment_status`, no unknown or stale state, no search bound (FR-10, FR-11, FR-13).
4. Existing hazards are hidden, and there is no what-if command (FR-07, FR-14).
5. No Evaluation records, revision check, agent tools, evidence view, or oracle (FR-03, FR-16, FR-17, FR-21, FR-22, FR-24).
