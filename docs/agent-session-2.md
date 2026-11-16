# Agent session 2: a loose question, a partial answer, and the fix

Recorded on 16 Nov 2026 with Claude Code, model `claude-opus-5-5`, against a fresh
copy of `stores/gas_plant.rl`. Unlike [session 1](agent-session.md), the question
names no permit and lists no changes. A coordinator would ask it that way.

Session A was interactive and ran before the fix. Session B ran headless
(`claude -p`) after it. Tool calls are shown as made. Tool results are
abridged to the fields that matter. The agent's answers are quoted in full
except where marked. Model output varies from run to run; the tool results do not.

## What this shows

- The verdict is only as good as the request it is given. Asked about "train B",
  the agent assessed one change it inferred (start K-220) and got CLEAR. The
  written permit, PTW-2201, makes five changes and is BLOCK.
- The agent hedged correctly ("I only asked about starting K-220"), but a hedge is
  easy to miss. The fix belongs in the tools, not the prompt.
- After the fix (`list_requests`, and `permit_id` on `assess_change` and
  `what_if`), the same loose question gets the written permit assessed exactly
  as written, and a BLOCK.

## Session A: before the fix (interactive)

Server: `python -m blindflange mcp --store gas.work.rl` (eight tools).

### Turn 1: "can train B be restarted?"

```
find_tags      {"text": "train B"}
  -> E-220 Train B aftercooler, V-220 suction scrubber, K-220 gas compressor, L-221, L-220S
assess_change  {"changes": [{"tag": "K-220", "to": "in_service"}]}
  -> COMPLETE, CLEAR, no findings (EVAL-3)
```

> Blind Flange says **CLEAR**. Restarting Train B gas compressor K-220 conflicts with no active permit and creates no hazard in the plant graph.
>
> (abridged) **Scope:** I only asked about starting K-220. If restarting the train also means opening valves or removing blinds (for example around V-220, E-220 or the suction lines L-220S/L-221), give me those changes and I'll check them together.

Starting K-220 on its own *is* CLEAR. That is not the job, though. The restart
permit also opens SDV-110, which joins the suction header to train C.

### Turn 2: "what if K-220 starts and SDV-110 is opened at the same time?"

```
assess_change  {"changes": [{"tag": "K-220", "to": "in_service"}, {"tag": "SDV-110", "to": "open"}]}
  -> COMPLETE, BLOCK (EVAL-4)
     PRESSURE_REACHES_TEMPORARY_BARRIER, PROVEN, target BF-230 (PTW-1230)
     path V-110 L-110G SDV-110 L-SUCT BV-231 L-231 V-230 L-230S K-230 L-230D RV-230 L-230R BF-230
     possible_sources: K-220
```

> Blind Flange says **BLOCK**. The cause is opening SDV-110, not starting K-220.
>
> (abridged) **K-220 is only a possible source.** Every component on its route has a known state, but the route runs against declared flow.

K-220 is only possible here because two changes are still missing. The permit's
XV-221, XV-223 and FV-222 give K-220 a route that runs with the declared flow.

### Turn 3: "explain finding 1 of EVAL-4 step by step"

```
explain_finding  {"evaluation_id": "EVAL-4", "finding": 1}
  -> 13 steps; SDV-110 changed_by_request; BV-231 open (observed 17:20);
     XV-231 closed beside L-SUCT and L-231; BF-230 installed, not pressure-tested
```

> (abridged) Step 5 is the weak point: BV-231 is open. It is a pressurisation bypass around XV-231, so gas can reach Train C even though XV-231 is shut. [...] Step 9: a compressor that is shut down is not a barrier. [...] Where the path can be cut: if any one of SDV-110, BV-231 or RV-230 is closed and confirmed, the path breaks.

### Turn 4: "what if BV-231 is closed and the restart permit PTW-2201 goes ahead?"

The agent searched the repository for the permit file and read it. That was
possible only because this session had file tools.

```
Grep "PTW-2201" in data/ ; Read data/permits/PTW-2201.yaml
what_if  {"changes": [{"tag": "BV-231", "to": "closed"}],
          "permit": {"id": "PTW-2201", "energises": ["K-220"],
                     "operates": [SDV-110 open, XV-221 open, XV-223 open, FV-222 open]}}
  -> COMPLETE, CLEAR (EVAL-5)
```

> Blind Flange says **CLEAR**, as long as BV-231 is closed first. [...]
> - **This was a what-if.** Nothing has changed in the store, and BV-231 is still recorded as open (since 17:20). The result only holds once BV-231 is actually closed and that's confirmed in the field.
> - **The permit doesn't record that it depends on BV-231.** I'd add `relies_on: [BV-231]` to PTW-2201.

## The fix

- `blindflange mcp --permits <dir>` gives the server a folder of written requests.
- `list_requests` (read-only) lists those whose tags are all in this plant: id,
  title, description, and what each starts, opens and closes.
- `assess_change` and `what_if` take `permit_id`. The file is loaded and validated
  as the CLI loads it, so the agent cannot drop or mistype a change.
- The server instructions say to call `list_requests` first, and to say which
  changes were assumed when no written request matches.
- The tag-matching field, a bare `baseline_verdict: PASS` before, is now
  `tag_matching_baseline` with a sentence saying what it is. In a trial run an
  agent had read the bare PASS as "the plant passed before the change".

Test: `test_a_written_request_by_id_is_assessed_exactly_as_written` in
`tests/test_agent.py` asserts the trap and the fix. Starting K-220 alone is CLEAR,
and `permit_id: PTW-2201` gives the same BLOCK, with the same findings, as the permit
passed by hand.

## Session B: after the fix (headless)

```
claude mcp add blindflange -- python -m blindflange mcp --store gas.work.rl --permits data/permits
claude -p "can train B be restarted?" --tools "" --allowedTools "mcp__blindflange__*"
```

`--tools ""` removes the file tools, so the agent cannot find the permit by
searching the repository. Only the blindflange tools are available.

```
list_requests  {}
  -> PTW-2201 "Restart compression on train B": energises K-220;
     operates SDV-110 open, XV-221 open, XV-223 open, FV-222 open
     (and the other gas plant requests, PTW-2202 to PTW-2207)
assess_change  {"permit_id": "PTW-2201"}
  -> COMPLETE, BLOCK (EVAL-1)
     PRESSURE_REACHES_TEMPORARY_BARRIER, PROVEN, target BF-230 (PTW-1230)
     sources: K-220, V-100, V-110, V-120, WH-MAN; possible: L-EXP
     path V-110 L-110G SDV-110 L-SUCT BV-231 L-231 V-230 L-230S K-230 L-230D RV-230 L-230R BF-230
```

> **No, not as written.** The tool returns a **BLOCK** on PTW-2201 (Restart compression on train B). The assessment is COMPLETE and recorded as EVAL-1.
>
> **Why:** Opening SDV-110 lets pressure reach **BF-230**. That blind flange is a temporary barrier that active permit **PTW-1230** (Train C PSV-230 recertification) relies on, and it has not been pressure-tested.
>
> The proven path:
>
> ```
> V-110 → L-110G → SDV-110 → L-SUCT → BV-231 → L-231 → V-230 → L-230S
>       → K-230 → L-230D → RV-230 → L-230R → BF-230
> ```
>
> So the train B restart sends gas back through the shared suction header into train C. It goes through BV-231 and the train C compressor to the blind at the relief valve, where the recertification job is working.
>
> - **The restart causes this.** It is not an existing hazard: it appears only when PTW-2201's changes are applied.
> - **Sources of pressure:** K-220, V-100, V-110, V-120 and WH-MAN are proven sources. C-400, MOL, P-310 and P-41C are other live services that also reach BF-230. L-EXP can only possibly reach it because its state isn't confirmed.
> - **A tag-only check would miss it.** PTW-2201 shares no tags with any active permit, so a check that only compares tags would pass it. The conflict only shows up by following the piping.
>
> **What it would take:** finish and close PTW-1230 first, or add a proven isolation between the suction header and train C. BV-231 is the obvious candidate. Then run the assessment again. I can test a version with BV-231 closed using `what_if` if you want.

K-220 is now a proven source, because all five of the permit's changes were applied.
