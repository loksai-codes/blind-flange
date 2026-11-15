# Blind Flange

Before a work permit is approved, Blind Flange walks the plant's piping graph in Relate to find conflicts with other open jobs, and shows the path that proves it.

Decision support only. This is not a safety system and has not been reviewed by a process safety engineer.

```
$ blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl

BLOCK  PTW-0511  Reinstate and start condensate pump A

  1. [BLOCK] PRESSURE_REACHES_TEMPORARY_BARRIER
     Pressure would reach BF-504, a temporary barrier that PTW-0504 relies on. It has not been pressure-tested.
     Other permit: PTW-0504  PSV-504 recertification (relief valve removed to workshop)
     Path (4 hops): P-A -> L-PD-A -> RLV-504 -> L-RL-504 -> BF-504

  Tag matching alone: no shared tags with any active permit, so it would pass.
```

## Use case

**The problem.** On a process plant every maintenance job needs a permit to work, and the equipment must be isolated first. Two permits can each look safe alone and conflict together. On Piper Alpha in 1988 a condensate pump was restarted while its relief valve was out for maintenance under a separate permit, with a blind flange covering the opening. The two permits named different equipment.

**The user.** The permit coordinator who approves permits on a shift. Their question: given every open permit and the current state of every valve and blind, is this job safe to start?

**The relationships that matter.**

- Which components are physically connected, and whether each one lets pressure through in its current state.
- Which components each permit opens up, relies on as an isolation, starts, or needs to operate.

The two permits in the example share no equipment tag, so matching permits by tag finds nothing. The conflict is a path through the piping. Close one valve on that path and the same request is clear:

```
$ blindflange set RLV-504 closed --store stores/condensate_unit.rl
RLV-504: open -> closed
$ blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
CLEAR  PTW-0511  Reinstate and start condensate pump A
```

## How it uses Relate

- **Mode:** single file
- **Why this mode:** One `.rl` file holds the plant, the valve and blind states and every open permit, so a shift can hand the whole picture to the next shift as one file, with no server or network. Judges can open the same file and query it.
- **What the graph models:**

```
(:Component)-[:CONNECTED_TO]-(:Component)      the piping: equipment, lines, valves, blinds
(:Permit)-[:WORKS_ON]->(:Component)            containment is broken here
(:Permit)-[:RELIES_ON]->(:Component)           isolation point protecting the work
(:Permit)-[:ENERGISES]->(:Component)           equipment the permit starts
(:Permit)-[:OPERATES {to}]->(:Component)       state change the permit needs
```

**The graph does the reasoning.** The main check is one Cypher statement, `queries/exposures.cypher`. It walks from every live pressure source with a quantified path pattern that filters on each hop, stops at closed valves and installed blinds, and joins the end of each path to the permits working there:

```cypher
MATCH path = SHORTEST 1 (s)
  ((a)-[:CONNECTED_TO]-(b)
    WHERE a.tag IN $assume_open
       OR (NOT a.state IN ['closed', 'installed', 'removed'] AND NOT a.tag IN $assume_closed)
  )+ (x:Component)
MATCH (q:Permit)-[r:WORKS_ON|RELIES_ON]->(x)
```

The `$assume_open` and `$assume_closed` parameters answer "what if this valve were opened?" without changing the store.

**Transactions as dry runs.** A permit is checked by writing it into the graph inside a transaction, querying, and rolling back. Approval is the same steps with a commit, so what was checked is exactly what is stored.

**Also used:** uniqueness constraints, and a full-text index for finding equipment tags from free text.

## Setup and run

Prerequisites: Python 3.10 or later, and git.

```
git clone <REPO_URL> && cd blind-flange
pip install -e .
blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
```

The third command prints the BLOCK result shown at the top of this page.

If your system blocks the `blindflange` launcher (Windows Application Control can refuse unsigned `.exe` files), use `python -m blindflange` in its place. Every command below works either way.

| Command | What it does |
| --- | --- |
| `blindflange check <permit.yaml> --store <file>` | Check a permit. Changes nothing. Add `--json` for machine output. |
| `blindflange approve <permit.yaml> --store <file>` | Check, then store the permit unless it is blocked. |
| `blindflange set <tag> <state> --store <file>` | Change a valve, blind or equipment state. Refused if it would break an isolation. |
| `blindflange close <permit-id> --store <file>` | Close a permit and list the isolations other permits still need. |
| `blindflange reach <tag> --store <file>` | Show what a component would pressurise. |
| `blindflange handover --store <file>` | Active permits, abnormal states and standing hazards. |
| `blindflange find "<text>" --store <file>` | Find equipment tags from free text. |
| `blindflange build <scenario.yaml> -o <file>` | Rebuild a store from YAML. |

For development: `pip install -e ".[dev]"`, then `make test`, `make eval` and `make stores`.

## Where the data lives

**Persistent store: `stores/condensate_unit.rl`** (single file, committed to this repo).

| Path | Contents |
| --- | --- |
| `stores/condensate_unit.rl` | The Relate store: 35 components, 37 connections, 2 active permits. |
| `schema/schema.cypher` | Graph model and data dictionary. |
| `queries/` | Every check as a standalone Cypher file. |
| `data/plants/`, `data/scenarios/`, `data/permits/` | The YAML the store is built from. |
| `eval/cases.yaml`, `eval/results.md` | Test cases and the generated comparison with tag matching. |

To inspect the store yourself:

```python
import relate
conn = relate.connect("stores/condensate_unit.rl", read_only=True)
print(conn.execute("MATCH (p:Permit)-[r]->(c:Component) RETURN p.id, type(r), c.tag").data())
```

The plant is an illustrative unit written for this project. It is inspired by published accounts of the Piper Alpha condensate pumps and is not a drawing of any real plant.

## Results

See `eval/results.md`. On ten author-written cases the graph check gives the expected verdict in all ten. Tag matching stops three of the six risky requests. These cases show what the checks do. They are not evidence of field performance.

## What already exists

Commercial control-of-work products manage permits and isolations together, including Sphera, Enablon and IntelliPERMIT. Blind Flange does not replace them. It is a small, open, single-file tool whose every finding can be inspected as a graph path.

## Limits

Pressure is modelled as reachability only: no flow direction, pressure levels or fluids. Electrical isolation is out of scope. See `docs/SPEC.md` for the full list.

## Tool and AI use disclosure

- Database: Relate by Neo4j (`relate-db` 1.0.1).
- Libraries: PyYAML, pytest.
- AI assistance: Claude (Anthropic) was used for research, design, and for writing code, tests and documentation in this repository, under the author's direction.

## Licence

MIT
