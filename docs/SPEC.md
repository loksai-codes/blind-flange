# Specification

## User and question
The user is the permit coordinator (area authority) on a process plant. Before
approving a permit they ask: given every other open permit and the current
state of every valve and blind, is this job safe to start?

Blind Flange answers with one of three verdicts and shows the path behind it.

| Verdict | Meaning |
| --- | --- |
| BLOCK | The permit conflicts with another permit or with the plant state. It is not stored. |
| HOLD | The permit can proceed with a condition, such as a shared isolation that must stay in place. |
| CLEAR | No conflict found. |

## Graph model
See `schema/schema.cypher` for the data dictionary.

- Every item on the piping is a `Component` node: equipment, line, valve, blind.
- `CONNECTED_TO` joins components that are physically connected. It is walked
  in both directions.
- A `Permit` node attaches to components with four relationships:
  `WORKS_ON` (containment broken here), `RELIES_ON` (isolation point),
  `ENERGISES` (equipment started or pressurised), `OPERATES {to}` (a state
  change the permit needs).

### Passability
Pressure passes through a component unless its state is `closed`, `installed`
or `removed`. A walk stops at the first such component, and that component is
the last node on the path.

### Live sources
A component is a live source if `source = true` and `state = 'in_service'`, or
if the permit being checked energises it.

## Checks

| Code | Severity | What it means | How it is found |
| --- | --- | --- | --- |
| PRESSURE_REACHES_OPEN_WORK | BLOCK | This permit would let pressure reach a place where another permit has opened the pipework. | Path walk from live sources, with this permit's state changes assumed. `exposures.cypher` |
| PRESSURE_REACHES_TEMPORARY_BARRIER | BLOCK | Pressure would reach a blind that is not pressure-tested and that a permit relies on. | Same walk. Target is a relied-on component with `integrity = 'temporary'`. |
| WORKSITE_NOT_ISOLATED | BLOCK | This permit's own worksite is reachable from a live source. The isolation list is incomplete. | Same walk, target is this permit's `WORKS_ON`. |
| ENERGISES_WORKSITE | BLOCK | This permit starts equipment another permit is working on. | One hop each side. `direct.cypher` |
| ISOLATION_REMOVED | BLOCK | This permit opens or removes a component another permit relies on. | One hop each side. `direct.cypher` |
| ISOLATION_NOT_IN_PLACE | BLOCK | A listed isolation is not closed or installed. | Property check. `direct.cypher` |
| SHARED_ISOLATION | HOLD | The same isolation protects two permits. | One hop each side. `direct.cypher` |

### How a check runs
1. Begin a transaction. Write the permit with status `requested`.
2. Read its state changes (`whatif.cypher`).
3. Run `exposures.cypher` twice: on the plant as it is, and with the permit's
   changes assumed. Anything in the second result and not the first is caused
   by this permit.
4. Run `direct.cypher`.
5. Roll back. For `approve`, repeat the write, apply the state changes and
   commit, unless the verdict is BLOCK.

### Baseline
`checks.baseline` is plain tag matching: does the request share a component
with an active permit? It is reported next to every verdict and in the eval
table, so the reader can see which conflicts need the path walk.

## Known simplifications
- Pressure is modelled as reachability. There is no flow direction, pressure
  level, fluid, or check-valve behaviour. A check valve is treated as open.
- A relief valve in place is treated as closed.
- Double block and bleed, vents and drains are not modelled as a pattern.
- Electrical and mechanical isolations are out of scope. Only process
  isolation is covered.
- The plant in `data/plants/condensate_unit.yaml` is illustrative and small.
- Nothing here has been reviewed by a process safety engineer yet.

These are listed so they can be stated in the README and raised with a
practitioner. Do not hide them.
