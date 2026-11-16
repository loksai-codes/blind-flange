# Blind Flange

Before a work permit is approved, Blind Flange walks the plant's piping graph in Relate to find conflicts with other open jobs, shows the path that proves each one, and refuses to say CLEAR when it cannot know.

Decision support only. This is not a safety system and has not been reviewed by a process safety engineer.

Project page: [`docs/index.html`](docs/index.html) · Sample evidence report: [`docs/report-PTW-2201.html`](docs/report-PTW-2201.html) · Agent session: [`docs/agent-session.md`](docs/agent-session.md)

```
$ blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl

BLOCK      PTW-0511  Reinstate and start condensate pump A
  assessment_status: COMPLETE    conflict_verdict: BLOCK    revision 1    EVAL-1

  1. [BLOCK] PRESSURE_REACHES_TEMPORARY_BARRIER
     Pressure would reach BF-504, a temporary barrier that PTW-0504 relies on. It has not been pressure-tested.
     Other permit: PTW-0504  PSV-504 recertification (relief valve removed to workshop)
     Path (4 hops): P-A -> L-PD-A -> RLV-504 -> L-RL-504 -> BF-504
     Also reached from: JT-DRUM, MOL, P-B

  Tag matching alone: no shared tags with any active permit, so it would pass.
```

## Use case

**The problem.** On a process plant every maintenance job needs a permit to work, and the equipment must be isolated first. Two permits can each look safe alone and conflict together. On Piper Alpha in 1988 a condensate pump was restarted while its relief valve was out for maintenance under a separate permit, with a blind flange covering the opening. The two permits named different equipment. That accident is the motivation here; this tool does not claim it would have prevented it.

**The user.** The permit coordinator who approves permits on a shift. Their question: given every open permit and the current state of every valve and blind, is this job safe to start? And when the answer depends on a valve nobody has checked since yesterday, they need to be told that, not given a green light.

**The relationships that matter.**

- Which components are physically connected, and whether each one lets pressure through in its current, observed state.
- Which components each permit opens up, relies on as an isolation, starts, or needs to operate.

The two permits in the example share no equipment tag, so matching permits by tag finds nothing. The conflict is a path through the piping. Close one valve on that path and the same request is clear. Mark that valve's state as unknown and the tool says it cannot decide:

```
$ blindflange set RLV-504=closed --store stores/condensate_unit.rl
RLV-504: open -> closed
$ blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
CLEAR      PTW-0511  Reinstate and start condensate pump A
  assessment_status: COMPLETE    conflict_verdict: CLEAR    revision 2    EVAL-3

$ blindflange set RLV-504=unknown --force --store stores/condensate_unit.rl
$ blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
INCOMPLETE PTW-0511  Reinstate and start condensate pump A
  assessment_status: INCOMPLETE    conflict_verdict: none    revision 3    EVAL-5

  1. [UNCONFIRMED] PRESSURE_REACHES_TEMPORARY_BARRIER  (possible)
     Pressure could reach BF-504, a temporary barrier that PTW-0504 relies on. ...
     Path (4 hops): P-A -> L-PD-A -> RLV-504 -> L-RL-504 -> BF-504
     Unconfirmed: RLV-504
```

On the larger illustrative gas plant (151 components), the same pattern hides behind a bypass. Train C's relief valve is out and a temporary blind is fitted. The isolation valve its permit lists is closed, but a small pressurisation bypass around it was left open. Restarting compression on train B reaches the blind in 12 hops, and no tag is shared:

```
$ blindflange check data/permits/PTW-2201.yaml --store stores/gas_plant.rl
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

**Every decision is kept in the same file.** Each assessment appends an `Evaluation` node with the request, the result and a snapshot of every input. `blindflange replay EVAL-1` rebuilds that snapshot in memory and re-runs the check. Writes check the `Store` revision, so an approval prepared against an older picture of the plant is refused.

**Also used:** uniqueness constraints, a full-text index for finding equipment tags from free text, `EXISTS { }` subqueries and `UNION`.

## Setup and run

Prerequisites: Python 3.10 or later, and git.

```
git clone https://github.com/loksai-codes/blind-flange.git && cd blind-flange
pip install -e .
blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
```

The third command prints the BLOCK result shown at the top of this page. It also appends an Evaluation record to the store; `git checkout stores/` puts the committed file back.

If your system blocks the `blindflange` launcher (Windows Application Control can refuse unsigned `.exe` files), use `python -m blindflange` in its place. Every command works either way.

| Command | What it does |
| --- | --- |
| `blindflange check <permit.yaml> --store <file>` | Assess a permit. Records an Evaluation; changes nothing else. |
| `blindflange whatif --set TAG=STATE [--permit <permit.yaml>] --store <file>` | Assess hypothetical changes, with or without a permit. Records an Evaluation; changes no plant state or permits. |
| `blindflange approve <permit.yaml> --store <file> [--revision N]` | Assess, then store the permit if CLEAR or HOLD, with its state changes recorded as planned. Records an Evaluation either way. Refused if the store has moved past revision N. |
| `blindflange set TAG=STATE --store <file>` | Record an observed state (`--by` names the observer). Refused unless CLEAR or HOLD (`--force` overrides). Records an Evaluation either way. |
| `blindflange close <permit-id> --store <file>` | Close a permit and list the isolations other permits still need. |
| `blindflange reach <tag> [--set TAG=STATE] --store <file>` | Show what a component could pressurise. |
| `blindflange handover --store <file>` | Active permits, abnormal and unconfirmed states, standing hazards. |
| `blindflange evaluations / show / replay <EVAL-n> --store <file>` | List, show and re-run recorded decisions. |
| `blindflange report <EVAL-n> --store <file>` | Write an HTML evidence page: the path, barriers beside it, and the plant. |
| `blindflange mcp --store <file>` | Serve agent tools over MCP (stdio). `assess_change` and `what_if` record an Evaluation; no tool changes plant state or permits. See below. |
| `blindflange find "<text>" --store <file>` | Find equipment tags from free text. |
| `blindflange validate <file.yaml>` | List every problem in a plant, scenario or permit file. |
| `blindflange build <scenario.yaml> -o <file>` | Rebuild a store from YAML. |

Every assessment returns two fields. `assessment_status` is COMPLETE, INCOMPLETE or ERROR. `conflict_verdict` is BLOCK, HOLD, CLEAR, or none when it cannot say. Exit codes: 0 CLEAR or HOLD, 1 error, 2 BLOCK or refused, 3 incomplete with no verdict.

**For an agent.** `blindflange mcp --store stores/gas_plant.rl` serves six tools over the Model Context Protocol: `assess_change`, `what_if`, `reach`, `handover`, `find_tags` and `get_evaluation`. It uses the standard library only. An agent can read a permit written in plain words, find the tags, and ask. The verdict comes from the same evaluator as the CLI. There is no tool to approve a permit or change plant state. For Claude Code:

```
claude mcp add blindflange -- python -m blindflange mcp --store stores/gas_plant.rl
```

[`docs/agent-session.md`](docs/agent-session.md) records Claude Code asked "can train B be restarted?" with and without the tool. Without it, the agent found no direct conflict and hedged. With it, the agent made one `assess_change` call, refused, and quoted the 12-hop path.

For development: `pip install -e ".[dev]"`, then `make test`, `make eval` and `make stores`. On a machine without `make`, run the commands in the `Makefile` directly.

## Where the data lives

**Persistent store: `stores/condensate_unit.rl`** (single file, committed to this repo).

| Path | Contents |
| --- | --- |
| `stores/condensate_unit.rl` | The headline store: 35 components, 37 connections, 2 active permits. |
| `stores/gas_plant.rl` | The larger store: 151 components, 185 connections, 5 active permits. |
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

See `eval/results.md`. On 33 author-written cases across both plants, the graph check gives the expected verdict, assessment status and finding codes in all 33. Seven of those cases expect "cannot say" or an error, and get it. Tag matching stops 7 of the 14 risky permit requests; it cannot assess a plain state change at all. An independent breadth-first walk (`eval/oracle.py`), written from the spec rather than from the Cypher, agrees with the graph on every hazard set in all 33 cases and on 120 random plants in the tests. Every recorded evaluation replays to the same result. The tests and eval pass from a fresh clone on Windows and on Linux.

These cases show what the checks do. They were written by the author, and they are not evidence of field performance.

## What already exists

Commercial control-of-work products manage permits and isolations together, including Sphera, Enablon and IntelliPERMIT. Blind Flange does not replace them. It is a small, open, single-file tool whose every finding can be inspected as a graph path and replayed from its record.

## Limits

- Pressure is modelled as reachability only: no flow direction, pressure levels, fluids or check-valve behaviour. That is why a finding can list several sources, some of them reached backwards through a pump.
- Only the final state is checked. Multi-step procedures are not modelled.
- Electrical isolation is out of scope.
- Observation staleness is measured against the store's `as_of` time (the time of the shift picture), or `--at`. The committed stores are fixed at their scenario time so results are reproducible.

See `docs/SPEC.md` for the full list.

## Tool and AI use disclosure

- Database: Relate by Neo4j (`relate-db` 1.0.1, pinned).
- Libraries: PyYAML, pytest.
- AI assistance: Claude (Anthropic), through Claude Code, was used for research, design, and for writing code, tests and documentation in this repository, under the author's direction. No language model is used at run time or in any decision.

## Licence

MIT
