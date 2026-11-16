# Review pack for a process or operations engineer

Blind Flange checks a proposed job, or a valve change, against the other open
permits by walking a graph of the plant's piping. It is decision support for the
permit coordinator, not a safety system. **Nobody with process or operations
experience has reviewed it yet.** This pack is what we would like you to look at.
It should take about 30 minutes. Any answer, including "this is wrong because...",
is useful.

Both plants are invented for the project. The small one is a condensate injection
unit loosely inspired by published accounts of the Piper Alpha condensate pumps.
The large one is a generic gas plant. Neither is a drawing of any real facility.

## 1. The modeling rules

**What the graph holds.** Every item on the piping is a component (equipment,
line, valve or blind) with a state, when that state was last observed, and by
whom. Connections join components that are physically connected. A permit links
to the components it opens up (`WORKS_ON`), relies on as isolations (`RELIES_ON`),
starts (`ENERGISES`), and needs operated (`OPERATES`, with the target state).

**Live sources.** A component is a live source if it is flagged as holding or
making pressure (separators, headers, running pumps and compressors) and is in
service, or if the job being checked starts it.

**The stopping rule.** From every live source the tool walks the connections:

| Component state | What the walk does |
| --- | --- |
| valve `closed`, blind `installed` | stops there (a barrier) |
| `removed` | stops there, and reaching it is a finding: the pipe is open |
| `unknown`, or not observed for 12 hours, or only *planned* by an approved permit | not trusted either way: the walk may pass it, but anything found that way is "possible", not "proven" |
| anything else, including a shut-down pump or compressor | pressure passes |

A check valve is one-way: going against its flow is only "possible".

**What counts as a conflict.** Pressure reaching a place where another permit has
opened the pipework, or a temporary (untested) blind another permit relies on, or
an open end. Also: the job opens a valve someone else relies on, starts equipment
someone is working on, lists an isolation that is not closed, or shares an
isolation or a worksite with another job.

**What the answer means.**

| Answer | Meaning |
| --- | --- |
| BLOCK | A proven conflict this job would cause, with the path. |
| HOLD | Needs review: a shared isolation or worksite, or a hazard already present that this job does not fix. |
| CLEAR | Nothing found, and every state that mattered was known and recent. |
| no verdict (INCOMPLETE) | Something that matters is unknown, stale, only planned, or against a check valve. The tool will not guess. |

The full rules are in [`SPEC.md`](SPEC.md).

## 2. The headline case, edge by edge

Train C is down for maintenance. Its relief valve PSV-230 is in the workshop, and
a temporary blind BF-230 is fitted (permit PTW-1230). That permit lists XV-231
(train C suction isolation, closed) and XV-233 (discharge isolation, closed).
The small-bore pressurisation bypass BV-231 around XV-231 was left open.

The request PTW-2201 restarts train B: open SDV-110, XV-221, XV-223 and FV-222,
and start K-220. The two permits share no tag. The tool blocks it on this proven
route (12 hops, from the HP separator):

| # | From | To | To is | State used |
| --- | --- | --- | --- | --- |
| 1 | V-110 | L-110G | line, HP separator gas outlet | in service |
| 2 | L-110G | SDV-110 | valve, compressor suction shutdown valve | open (opened by the request) |
| 3 | SDV-110 | L-SUCT | line, compressor suction header | in service |
| 4 | L-SUCT | BV-231 | valve, train C suction pressurisation bypass (small bore) | open |
| 5 | BV-231 | L-231 | line, train C suction line | in service |
| 6 | L-231 | V-230 | vessel, train C suction scrubber | in service |
| 7 | V-230 | L-230S | line, train C compressor suction | in service |
| 8 | L-230S | K-230 | compressor, train C gas compressor | shut down (passes pressure) |
| 9 | K-230 | L-230D | line, train C compressor discharge | in service |
| 10 | L-230D | RV-230 | valve, train C relief valve inlet block valve | open |
| 11 | RV-230 | L-230R | line, train C relief line | in service |
| 12 | L-230R | BF-230 | blind fitted in place of PSV-230, temporary | installed (the walk stops here) |

The same blind is also reached, in the gas service, from K-220, the export
pipeline L-EXP, V-100, V-120 and the wellhead manifold. It is also reached from
C-400, MOL, P-310 and P-41C. Those four are in other services (condensate, oil,
glycol) and get there only through connections the tool does not treat as
deliberate tie-ins, so it does not list them as sources.

Edges we expect you might question:

- **8 to 9, through the stopped compressor K-230.** We let pressure pass a stopped
  machine from suction to discharge (settle-out). Is that how you would treat it?
- **4, the bypass BV-231.** The scenario assumes a small-bore pressurisation bypass
  around a suction isolation valve is left open and is not on the isolation list.
  Is that plausible, and would your isolation procedure catch it anyway?
- **10, RV-230 open with the PSV removed.** We assume the relief block valve stays
  open and the blind is fitted at the PSV inlet flange.

The evidence report for this case, with the path drawn and the barriers beside
each step, is [`report-PTW-2201.html`](report-PTW-2201.html).

## 3. Known simplifications

- **No pressure levels, fluids or flow rates.** Reachability only. Instrument air
  is treated the same as HP gas, which is one reason utilities are kept as
  separate services.
- **Flow direction only on check valves.** Everything else carries pressure both
  ways, so a hazard can be reached backwards through a stopped pump.
- **Final state only.** A sequence of steps (isolate, vent, drain, then break) is
  not modelled.
- **No double block and bleed** as a pattern; no vents and drains as part of
  proving an isolation.
- **Process isolation only.** Electrical and mechanical isolation are out of scope.
- **Staleness is a single threshold** (12 hours by default, one shift).
- **A closed valve that is not on the permit's isolation list still holds.** The
  tool does not flag it as missing from the permit.

## 4. Three questions

1. **Is the stopping rule realistic?** Closed valves and installed blinds stop
   pressure; a single closed valve counts as an isolation; a stopped pump or
   compressor passes pressure; an unknown or 12-hour-old state is not trusted.
   Where would you draw these lines differently, for example requiring double
   block and bleed for some jobs?

2. **How should a removed component be treated?** We treat a removed valve or
   spool as an open end: pressure reaching it escapes and is a finding, and it
   does not continue past the gap. We refuse "removed" for a blind, because it
   could mean the blind or the spool it closes. Is that how you would record it
   on a permit or isolation certificate?

3. **Which links look wrong?** In the headline path above, or anywhere in
   `data/plants/gas_plant.yaml` (generated by `data/plants/make_gas_plant.py`):
   which connections, states or services would you challenge? For example, should
   fuel gas reach a compressor through its seal gas line, or nitrogen reach a
   scrubber through a purge connection, as we have them?

## How to reply

Open an issue on the repository, or send notes in any form. If you are willing to
be credited, say how. Until a review has happened, the README says
"Practitioner review: pending".
