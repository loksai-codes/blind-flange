# Specification

The result rules and requirements, with their status, are in `docs/REQUIREMENTS.md`.
This file describes the model and the checks in words.

## User and question
The user is the permit coordinator (area authority) on a process plant. Before
approving a permit, or changing a valve, they ask: given every other open permit
and the current state of every valve and blind, is this safe to start?

Blind Flange answers with two fields and shows the path behind every finding.

| `assessment_status` | Meaning |
| --- | --- |
| COMPLETE | Every state that matters is known and current, and the search finished inside its bound. |
| INCOMPLETE | A state that matters is unknown or stale, or the search hit its bound. |
| ERROR | The request or the store is not usable (unknown tag, ambiguous change, stale revision). |

| `conflict_verdict` | Meaning |
| --- | --- |
| BLOCK | A proven conflict this request introduces. The request is not stored. |
| HOLD | A proven condition needs review: a shared isolation, or a hazard that exists already and the request does not remove. |
| CLEAR | No conflict found, and the assessment is COMPLETE. |
| none | Incomplete with no proven conflict, or an error. |

## Graph model
See `schema/schema.cypher` for the data dictionary.

- Every item on the piping is a `Component` node: equipment, line, valve, blind.
  Each carries a `state`, `observed_at` and `observed_by`.
- `CONNECTED_TO` joins components that are physically connected. It is walked
  in both directions.
- A `Permit` node attaches to components with four relationships:
  `WORKS_ON` (containment broken here), `RELIES_ON` (isolation point),
  `ENERGISES` (equipment started or pressurised), `OPERATES {to}` (a state
  change the permit needs). Permit `status` is authorization only.
- One `Store` node per file holds the revision, the time of the shift picture
  (`as_of`) and the observation age limit.
- One `Evaluation` node per assessment holds the request, the result and a
  snapshot of every input.

### Passability (the one rule)
Also in `queries/exposures.cypher`, `queries/bound.cypher`, `queries/reach.cypher`
and `src/blindflange/model.py`. Change them together.

| State | Effect on a walk |
| --- | --- |
| `closed`, `installed` | Barrier. Pressure reaches it and stops. |
| `removed` | Open end. Pressure reaches it, escapes, and does not continue. Reaching it is a finding. |
| `unknown` (or no state) | Never a barrier. The walk may pass it, but only in the POSSIBLE pass. |
| any state observed before `as_of - max_age_hours` | Stale: treated like `unknown`. |
| a `planned_state` (written by approval) | Planned: treated like `unknown` until someone observes the component. |

A connection may declare one-way flow: `[A, B, forward]` in the plant file
means pressure flows from A to B. Every connection through a check valve must
declare it. A hop against declared flow is allowed only in the POSSIBLE pass,
so a route that needs one is reported as POSSIBLE, labelled "against declared
flow" with the hops listed. A hazard proven from one source is not made
uncertain by another source that only reaches it against flow.
| anything else | Passes. |

A blind is `installed` or `not_installed`. `removed` is rejected for a blind,
because it could mean the blind or the spool it closes.

### Assessment time and store mode
Every assessment has a time. It is `--at` if given; otherwise it depends on the
store's mode:

| Mode | Made by | Assessed at |
| --- | --- | --- |
| snapshot | `build` (the committed stores) | the store's `as_of`, the time of the picture, so the answer never depends on today's date |
| live | `shift start --from <store> -o <live.rl>` | the current time |

An observation is stale when `observed_at` is older than the assessment time
minus `max_age_hours` (default 12, one shift; set by the scenario's
`max_observation_age_hours` or `shift start --max-age-hours`). `freshness` lists
stale observations. The resolved assessment time is recorded in each Evaluation,
so a live evaluation replays at the time it was made.

### Live sources
A component is a live source if `pressure_source = true` and `state = 'in_service'`,
or if the request being assessed energises it. Setting a pressure source to
`in_service` through `set` is the same as starting it. In the POSSIBLE pass, a
pressure source whose state is unknown or stale also counts.

## Checks

| Code | Nominal severity | What it means | How it is found |
| --- | --- | --- | --- |
| PRESSURE_REACHES_OPEN_WORK | BLOCK | Pressure reaches a place where another permit has opened the pipework. | Walk from live sources. `exposures.cypher` |
| PRESSURE_REACHES_TEMPORARY_BARRIER | BLOCK | Pressure reaches a blind that is not pressure-tested and that a permit relies on. | Same walk. Target is a relied-on component with `integrity = 'temporary'`. |
| PRESSURE_REACHES_OPEN_END | BLOCK | Pressure reaches a removed component: the pipe is open there. | Same walk. Target has `state = 'removed'` and no permit works on it. |
| WORKSITE_NOT_ISOLATED | BLOCK | The request's own worksite is reachable from a live source. | Same walk, target is the request's `WORKS_ON`. |
| ENERGISES_WORKSITE | BLOCK | The request starts equipment another permit is working on. | One hop each side. `direct.cypher` |
| ISOLATION_REMOVED | BLOCK | The request opens or removes a component another permit relies on. | One hop each side. `direct.cypher` |
| ISOLATION_NOT_IN_PLACE | BLOCK | A listed isolation is not confirmed closed or installed. | Property check. `direct.cypher` |
| SHARED_ISOLATION | HOLD | The same isolation protects two permits. | One hop each side. `direct.cypher` |
| WORKSITE_SHARED | HOLD | Another active permit already works on the same component. A modeled dependency that requires review. | One hop each side. `direct.cypher` |

Each finding also has an `origin` and a `certainty`, which set its effect:

| Origin | Certainty | Effect on the result |
| --- | --- | --- |
| introduced | PROVEN | The nominal severity (BLOCK, or HOLD for a shared isolation). |
| existing | PROVEN | HOLD. The hazard was there before; the request does not remove it. |
| either | POSSIBLE | UNCONFIRMED. Decides nothing; makes the assessment INCOMPLETE. |

Path findings carry the shortest path as evidence, the sources that reach the
same target, and the unconfirmed components on the path. Sources are listed only
if they are in the target's `service` or reach it through a declared tie-in
(`tie_ins` in the plant file, as [from, to]); the others go in
`other_service_sources`. This is display only: every source still counts
towards the verdict, because pressure levels are not modelled. One-hop findings carry
the graph edges that prove them.

### How an assessment runs
1. Validate the request (a permit, or state changes) and any what-if changes
   against the store. Problems give an ERROR result.
2. Begin a transaction.
3. Run `exposures.cypher` in both passes on the plant as it is ("before"), and
   `bound.cypher`.
4. Apply the what-if changes. Write the request as a `requested` permit and apply
   its state changes (`apply.cypher`).
5. Run `exposures.cypher` in both passes again ("after"), `bound.cypher`,
   `direct.cypher` and `baseline.cypher`.
6. Roll back.
7. Sort the rows into findings: a (permit, target, relation, source) present
   after but not before is introduced; present in both is existing (remaining);
   present before only is resolved.
8. Decide the two result fields, then append an `Evaluation` with a snapshot.

`approve` and `set` run the same assessment, then, if the verdict is CLEAR or
HOLD, write in a committed transaction that also checks and bumps the store
revision.

- `approve` stores the permit as active and records its state changes as
  **planned** (`planned_state`, `planned_by`, `planned_at`). It does not touch
  the observed `state`, `observed_at` or `observed_by`. A planned state is
  unconfirmed: it is never a barrier in the PROVEN pass, so a route through it
  gives a POSSIBLE finding and an INCOMPLETE result, never CLEAR.
- `set TAG=STATE --by <observer>` records an observation. It makes the state
  verified and clears any plan on that component.
- A what-if (`whatif --set`) may assume a planned state hypothetically.

### Search bound
Every walk is bounded (default 100 hops, at most 499 because Relate refuses
literal bounds above 500). `bound.cypher` walks one hop further and counts
components whose shortest route from a possible source exceeds the bound. Any
such component makes the assessment INCOMPLETE.

### Baseline
`queries/baseline.cypher` is plain tag matching: does the request name a
component an active permit also names? It is reported next to every permit
verdict and in the eval table, so the reader can see which conflicts need the
path walk.

### Oracle
`eval/oracle.py` is a plain breadth-first search written from this file, not
from the Cypher. The eval and `tests/test_oracle.py` (120 random plants with
loops, unknown, stale and removed states) check that it computes the same
hazard sets as the graph.

## Known simplifications
- Pressure is modelled as reachability. There is no pressure level or fluid.
  Flow direction exists only where it is declared (every check valve); elsewhere
  a connection carries pressure both ways, and a pump or compressor that is shut
  down passes pressure in both directions.
- A relief valve in place is treated as closed.
- Only the final state is checked. Multi-step procedures are not modelled.
- Double block and bleed, vents and drains are not modelled as a pattern.
- Electrical and mechanical isolations are out of scope. Only process
  isolation is covered.
- An isolation that is not listed on a permit but is closed still holds; it is
  not flagged as missing from the permit.
- Staleness is measured against the store's `as_of` or `--at`, not the wall
  clock, so a committed store gives the same answer every time.
- Both plants are illustrative and small next to a real facility.
- Nothing here has been reviewed by a process safety engineer yet.

These are listed so they can be stated in the README and raised with a
practitioner. Do not hide them.
