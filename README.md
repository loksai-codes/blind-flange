# Blind Flange

Before a work permit is approved, Blind Flange walks the plant's piping graph in Relate to find conflicts with other open jobs, shows the path that proves each one, and refuses to say CLEAR when it cannot know.

Decision support only. This is not a safety system and has not been reviewed by a process safety engineer.

Practitioner review: pending. [`docs/REVIEW_PACK.md`](docs/REVIEW_PACK.md) is what we have asked a process or operations engineer to look at.

Project page: [`docs/index.html`](docs/index.html) · Sample evidence report: [`docs/report-PTW-2201.html`](docs/report-PTW-2201.html) · Agent session: [`docs/agent-session.md`](docs/agent-session.md)

```
$ python -m blindflange check data/permits/PTW-0511.yaml --store work.rl

BLOCK      PTW-0511  Reinstate and start condensate pump A
  assessment_status: COMPLETE    conflict_verdict: BLOCK    revision 1    EVAL-1

  1. [BLOCK] PRESSURE_REACHES_TEMPORARY_BARRIER
     Pressure would reach BF-504, a temporary barrier that PTW-0504 relies on. It has not been pressure-tested.
     Other permit: PTW-0504  PSV-504 recertification (relief valve removed to workshop)
     Path (4 hops): P-A -> L-PD-A -> RLV-504 -> L-RL-504 -> BF-504
     Also reached from: JT-DRUM, P-B
     Not listed: 1 source in other services with no declared tie-in (--json shows them)

  Tag matching alone: no shared tags with any active permit, so it would pass.
```

`work.rl` is a copy of the committed `stores/condensate_unit.rl` (see [Setup and run](#setup-and-run)), so the committed store never changes.

## Use case

**The problem.** On a process plant every maintenance job needs a permit to work, and the equipment must be isolated first. Two permits can each look safe alone and conflict together. On Piper Alpha in 1988 a condensate pump was restarted while its relief valve was out for maintenance under a separate permit, with a blind flange covering the opening. The two permits named different equipment. That accident is the motivation here; this tool does not claim it would have prevented it.

**The user.** The permit coordinator who approves permits on a shift. Their question: given every open permit and the current state of every valve and blind, is this job safe to start? And when the answer depends on a valve nobody has checked since yesterday, they need to be told that, not given a green light.

**The relationships that matter.**

- Which components are physically connected, and whether each one lets pressure through in its current, observed state.
- Which components each permit opens up, relies on as an isolation, starts, or needs to operate.

The two permits in the example share no equipment tag, so matching permits by tag finds nothing. The conflict is a path through the piping. Close one valve on that path and the same request is clear. Mark that valve's state as unknown and the tool says it cannot decide:

```
$ python -m blindflange set RLV-504=closed --by "operator round" --store work.rl
RLV-504: open -> closed
$ python -m blindflange check data/permits/PTW-0511.yaml --store work.rl
CLEAR      PTW-0511  Reinstate and start condensate pump A
  assessment_status: COMPLETE    conflict_verdict: CLEAR    revision 2    EVAL-3

$ python -m blindflange set RLV-504=unknown --force --by "operator round" --store work.rl
$ python -m blindflange check data/permits/PTW-0511.yaml --store work.rl
INCOMPLETE PTW-0511  Reinstate and start condensate pump A
  assessment_status: INCOMPLETE    conflict_verdict: none    revision 3    EVAL-5

  1. [UNCONFIRMED] PRESSURE_REACHES_TEMPORARY_BARRIER  (possible)
     Pressure could reach BF-504, a temporary barrier that PTW-0504 relies on. ...
     Path (4 hops): P-A -> L-PD-A -> RLV-504 -> L-RL-504 -> BF-504
     Unconfirmed: RLV-504
```

On the larger illustrative gas plant (151 components), the same pattern hides behind a bypass. Train C's relief valve is out and a temporary blind is fitted. The isolation valve its permit lists is closed, but a small pressurisation bypass around it was left open. Restarting compression on train B reaches the blind in 12 hops, and no tag is shared:

```
$ python -m blindflange check data/permits/PTW-2201.yaml --store gas.work.rl
BLOCK      PTW-2201  Restart compression on train B
  1. [BLOCK] PRESSURE_REACHES_TEMPORARY_BARRIER
     Pressure would reach BF-230, a temporary barrier that PTW-1230 relies on. It has not been pressure-tested.
     Path (12 hops): V-110 -> L-110G -> SDV-110 -> L-SUCT -> BV-231 -> L-231 -> V-230 -> L-230S -> K-230 -> L-230D -> RV-230 -> L-230R -> BF-230
```

## How it uses Relate

- **Mode:** single file
- **Why this mode:** One `.rl` file holds the plant, the observed valve and blind states, every open permit and a record of every decision, so a shift can hand the whole picture to the next shift as one file, with no server or network. Judges can open the same file and query it.
- **What the graph models:**

```
(:Component)-[:CONNECTED_TO]-(:Component)      the piping: equipment, lines, valves, blinds
                                               each with state, observed_at, observed_by
(:Permit)-[:WORKS_ON]->(:Component)            containment is broken here
(:Permit)-[:RELIES_ON]->(:Component)           isolation point protecting the work
(:Permit)-[:ENERGISES]->(:Component)           equipment the permit starts
(:Permit)-[:OPERATES {to}]->(:Component)       state change the permit needs
(:Store {revision, as_of})                     one per file: the revision every write bumps
(:Evaluation {request, result, snapshot})      every decision, with the inputs to replay it
```

**The graph does the reasoning.** The main check is one Cypher statement, [`queries/exposures.cypher`](queries/exposures.cypher). It walks from every live pressure source with a quantified path pattern that filters every hop, stops at closed valves and installed blinds, and joins the end of each path to the permits working there:

```cypher
MATCH path = SHORTEST 1 (s)
  ((a)-[:CONNECTED_TO]-(b)
    WHERE ( NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed', 'unknown']
            AND coalesce(a.observed_at, '') >= $stale_before )
       OR ( $possible AND (coalesce(a.state, 'unknown') = 'unknown'
                           OR coalesce(a.observed_at, '') < $stale_before) )
  ){0,100} (x:Component)
OPTIONAL MATCH (q:Permit)-[r:WORKS_ON|RELIES_ON]->(x)
```

The same statement runs twice. With `$possible = false` the walk only passes components whose state is known and current, so a finding is PROVEN. With `$possible = true` it may also pass a valve nobody has confirmed, so a finding that only appears then is POSSIBLE. A POSSIBLE finding never blocks on its own. It makes the result INCOMPLETE, and the verdict is withheld.

**A search that stops early never says CLEAR.** Relate only accepts a literal path bound, and refuses explicit bounds above 500 hops. Every walk is bounded, and [`queries/bound.cypher`](queries/bound.cypher) walks one hop further to count components the bounded walk could have missed. If there are any, the result is INCOMPLETE.

**Transactions as dry runs.** A request is assessed by writing it into the graph inside a transaction, applying its state changes, querying, and rolling back. Approval is the same steps with a commit, so what was checked is exactly what is stored. The walk runs before and after the change, so hazards the request introduces are separated from hazards that already exist. An existing hazard gives HOLD, never CLEAR.

**Every decision is kept in the same file.** Each assessment appends an `Evaluation` node with the request, the result and a snapshot of every input. `python -m blindflange replay EVAL-1` rebuilds that snapshot in memory and re-runs the check. Writes check the `Store` revision, so an approval prepared against an older picture of the plant is refused.

**Also used:** uniqueness constraints, a full-text index for finding equipment tags from free text, `EXISTS { }` subqueries and `UNION`.

## Setup and run

Prerequisites: Python 3.10 or later, and git.

Quick start:

```
git clone https://github.com/loksai-codes/blind-flange.git && cd blind-flange
python -m venv .venv
source .venv/bin/activate                # Windows: .venv\Scripts\activate
pip install -e .
cp stores/condensate_unit.rl work.rl     # Windows: copy stores\condensate_unit.rl work.rl
python -m blindflange check data/permits/PTW-0511.yaml --store work.rl
```

The last command prints the BLOCK result shown at the top of this page. Every assessment appends an Evaluation record to the store it is given, so the examples work on `work.rl`, a gitignored copy, and the committed stores stay exactly as they are. For the gas plant, copy `stores/gas_plant.rl` to `gas.work.rl` the same way.

`pip install` also creates a `blindflange` launcher, which works in place of `python -m blindflange`. Windows Application Control can refuse that unsigned `.exe`; `python -m blindflange` always works.

| Command | What it does |
| --- | --- |
| `python -m blindflange check <permit.yaml> --store <file>` | Assess a permit. Records an Evaluation; changes nothing else. |
| `python -m blindflange whatif --set TAG=STATE [--permit <permit.yaml>] --store <file>` | Assess hypothetical changes, with or without a permit. Records an Evaluation; changes no plant state or permits. |
| `python -m blindflange approve <permit.yaml> --store <file> [--revision N]` | Assess, then store the permit if CLEAR or HOLD, with its state changes recorded as planned. Records an Evaluation either way. Refused if the store has moved past revision N. |
| `python -m blindflange set TAG=STATE --by <observer> --store <file>` | Record an observed state (`--by` names the observer). Refused unless CLEAR or HOLD (`--force` overrides). Records an Evaluation either way. |
| `python -m blindflange close <permit-id> --store <file>` | Close a permit and list the isolations other permits still need. |
| `python -m blindflange reach <tag> [--set TAG=STATE] --store <file>` | Show what a component could pressurise. |
| `python -m blindflange handover --store <file>` | Active permits, abnormal and unconfirmed states, standing hazards. Leaves the file unchanged. |
| `python -m blindflange evaluations / show / replay <EVAL-n> --store <file>` | List, show and re-run recorded decisions. |
| `python -m blindflange report <EVAL-n> --store <file>` | Write an HTML evidence page: the path, barriers beside it, and the plant. |
| `python -m blindflange mcp --store <file>` | Serve agent tools over MCP (stdio). `assess_change` and `what_if` record an Evaluation; no tool changes plant state or permits. See below. |
| `python -m blindflange shift start --from <store> -o <live.rl>` | Copy a store and make the copy live: assessed at the current time from then on. |
| `python -m blindflange freshness --store <file>` | List observations older than the store's threshold at the assessment time. |
| `python -m blindflange find "<text>" --store <file>` | Find equipment tags from free text. |
| `python -m blindflange validate <file.yaml>` | List every problem in a plant, scenario or permit file. |
| `python -m blindflange build <scenario.yaml> -o <file>` | Rebuild a store from YAML. |

Every assessment returns two fields. `assessment_status` is COMPLETE, INCOMPLETE or ERROR. `conflict_verdict` is BLOCK, HOLD, CLEAR, or none when it cannot say. Exit codes: 0 CLEAR or HOLD, 1 error, 2 BLOCK or refused, 3 incomplete with no verdict.

**For an agent.** `python -m blindflange mcp --store gas.work.rl` serves six tools over the Model Context Protocol: `assess_change`, `what_if`, `reach`, `handover`, `find_tags` and `get_evaluation`. It uses the standard library only. An agent can read a permit written in plain words, find the tags, and ask. The verdict comes from the same evaluator as the CLI. There is no tool to approve a permit or change plant state. For Claude Code:

```
claude mcp add blindflange -- python -m blindflange mcp --store gas.work.rl
```

[`docs/agent-session.md`](docs/agent-session.md) records Claude Code asked "can train B be restarted?" with and without the tool. Without it, the agent found no direct conflict and hedged. With it, the agent made one `assess_change` call, refused, and quoted the 12-hop path.

For development, inside the virtual environment:

| Make target | Plain command (no `make` needed) |
| --- | --- |
| `make install` | `pip install -e ".[dev]"` |
| `make test` | `python -m pytest -q` |
| `make eval` | `python eval/compare.py` (writes `eval/results.md`) |
| `make stores` | `python -m blindflange build data/scenarios/condensate_unit.yaml -o stores/condensate_unit.rl`, and the same for `gas_plant` |
| `make demo` | copy both stores to `work.rl` and `gas.work.rl`, then `python -m blindflange check data/permits/PTW-0511.yaml --store work.rl` and `python -m blindflange check data/permits/PTW-2201.yaml --store gas.work.rl` |

## Where the data lives

**Persistent store: `stores/condensate_unit.rl`** (single file, committed to this repo).

| Path | Contents |
| --- | --- |
| `stores/condensate_unit.rl` | The headline store: 35 components, 37 connections, 2 active permits. |
| `stores/gas_plant.rl` | The larger store: 151 components, 184 connections, 5 active permits. |
| `schema/schema.cypher` | Graph model and data dictionary. |
| `queries/` | Every check as a standalone Cypher file; `store.cypher` holds the named plumbing statements. |
| `data/plants/`, `data/scenarios/`, `data/permits/` | The YAML the stores are built from. `make_gas_plant.py` generates the gas plant. |
| `eval/cases.yaml`, `eval/results.md`, `eval/oracle.py` | Test cases, the generated comparison, and the independent traversal used to check the Cypher. |
| `docs/SPEC.md`, `docs/REQUIREMENTS.md` | The model, the checks and the result rules in words; requirements with their status. |

To inspect a store yourself:

```python
import relate
conn = relate.connect("stores/gas_plant.rl", read_only=True)
print(conn.execute("MATCH (p:Permit)-[r]->(c:Component) RETURN p.id, type(r), c.tag").data())
```

Both plants are illustrative and were written for this project. The condensate unit is inspired by published accounts of the Piper Alpha condensate pumps and is not a drawing of any real plant. The gas plant is invented.

## Results

See `eval/results.md` and `docs/stats.json` (both generated; `python scripts/stats.py` refreshes the numbers on this page). On <!--stat:eval_cases-->35<!--/stat--> author-written cases across both plants, the graph check gives the expected verdict, assessment status and finding codes in <!--stat:eval_matched-->35<!--/stat-->. <!--stat:eval_no_verdict-->8<!--/stat--> of those cases expect "cannot say" or an error, and get it. Tag matching stops <!--stat:tag_matching_stopped-->8 of 15<!--/stat--> risky permit requests; it cannot assess a plain state change at all. An independent breadth-first walk (`eval/oracle.py`), written from the spec rather than from the Cypher, agrees with the graph on every hazard set in <!--stat:oracle_agreed-->35<!--/stat--> cases and on <!--stat:random_plants-->120<!--/stat--> random plants in the tests. <!--stat:replay_same-->35<!--/stat--> recorded evaluations replay to the same result. <!--stat:tests_passed-->258<!--/stat--> automated tests pass, and <!--stat:mutations_caught_text-->12 of 12<!--/stat--> deliberate mutations of the checks (`scripts/mutations.py`) are caught by at least one test. CI runs the install, the tests and the eval on Linux, macOS and Windows.

These cases show what the checks do. They were written by the author, and they are not evidence of field performance.

## What already exists

Commercial control-of-work products manage permits and isolations together, including Sphera, Enablon and IntelliPERMIT. Blind Flange does not replace them. It is a small, open, single-file tool whose every finding can be inspected as a graph path and replayed from its record.

## Limits

- Pressure levels are not modelled. Pressure is reachability: no pressure levels or fluids. Flow direction is declared only on one-way connections (every check valve); a route against declared flow is reported as POSSIBLE, "against declared flow", never PROVEN. Everywhere else a connection carries pressure both ways, so a hazard can still be reached backwards through a stopped pump.
- Each component has a `service` (process gas, condensate, fuel gas, nitrogen, instrument air and so on), and each plant declares the tie-ins where one service may legitimately enter another (`tie_ins` in the plant file). "Also reached from" lists only sources in the target's service or a declared tie-in; the others are counted, shown with `--json`, and still count towards the verdict. Instrument air and fire water have no connection to process piping.
- Only the final state is checked. Multi-step procedures are not modelled.
- Electrical isolation is out of scope.
- Every store has a mode. A **snapshot** (what `build` makes, and what is committed here) is assessed at its `as_of`, the time of the picture, so it gives the same answer on any day. A **live** store (`shift start`) is assessed at the current time. `--at` overrides either. Every result prints the assessment time and the mode.
- The staleness threshold is 12 hours by default (one shift): an observation older than that, measured back from the assessment time, is unconfirmed and can give INCOMPLETE but never CLEAR. Set it per scenario with `max_observation_age_hours`, or per live store with `shift start --max-age-hours`. `freshness` lists what has gone stale.

See `docs/SPEC.md` for the full list.

## Tool and AI use disclosure

- Database: Relate by Neo4j (`relate-db` 1.0.1, pinned).
- Libraries: PyYAML, pytest.
- AI assistance: Claude (Anthropic), through Claude Code, was used for research, design, and for writing code, tests and documentation in this repository, under the author's direction. No language model is used at run time or in any decision.

## Licence

MIT
