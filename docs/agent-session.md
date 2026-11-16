# Agent session: can train B be restarted?

Recorded on 16 Nov 2026 with Claude Code in headless mode (`claude -p`), model
`claude-opus-5-5`, against a fresh copy of `stores/gas_plant.rl`. The same question was asked
twice: once with no tools, and once with `blindflange mcp` connected and all eight
of its tools allowed. Nothing below is edited except where marked "abridged". The
raw stream-json logs were kept outside the repo. Model output varies from run to
run; the tool results do not.

This is the gate for milestone M2: the agent refuses the restart and quotes the
path. It also shows the exploration tools (`trace_path`, `explain_finding`) in
use: the agent checked for itself which isolation the route gets around.

## The question (identical in both runs)

```
You are helping the permit coordinator on the night shift of a gas processing plant.

Active permits:
- PTW-1230 Train C PSV-230 recertification. Works on PSV-230. Isolations: BF-230 (temporary blind), XV-231, XV-233.
- PTW-1310 Dry gas filter element change. Works on F-300. Isolations: XV-301, XV-302, DR-300.
- PTW-1420 Condensate pump B mechanical seal replacement. Works on P-41B. Isolations: SV-41B, DV-41B, DR-41B.
- PTW-1505 Export pig launcher door inspection. Works on PL-500. Isolations: XV-501, XV-502.
- PTW-1610 Replace train C nitrogen purge spool. Works on L-N2-610. Isolations: XV-610, XV-611.

New request, PTW-2201 "Restart compression on train B": open SDV-110, XV-221, XV-223 and FV-222, and start compressor K-220.

Should PTW-2201 be approved now? First line: APPROVE or DO NOT APPROVE. Then explain in at most six lines.
```

## Without the tool

No tools were available (`--tools ""` and an empty MCP config). The agent had only
the permit list above.

> **DO NOT APPROVE (yet)**
> 
> 1. No direct tag clash: SDV-110, XV-221, XV-223, FV-222 and K-220 aren't on any active permit. Note that XV-221/223 (train B) are not XV-231/233 (PTW-1230, train C).
> 2. Restarting compression pressurizes systems beyond those tags. The list doesn't show what SDV-110 feeds or where K-220 discharges.
> 3. PTW-1310 (F-300 dry gas filter) and PTW-1505 (PL-500 export launcher, door open) are likely downstream of compression. They rely on single valves (XV-301/302, XV-501/502) with no listed blind or bleed.
> 4. Check whether SDV-110 is a common inlet or header shared with train C (PTW-1230 / PTW-1610). Check whether the N2 purge supply to train B is affected by the L-N2-610 spool removal.
> 5. Approve once the P&IDs or the area authority confirm that train B's flow path doesn't reach F-300, PL-500 or train C. If it does, those isolations must be shown adequate against K-220 discharge pressure.
> 6. If confirmed clean, PTW-2201 can be approved. Nothing in the tag list itself blocks it.

It finds no direct conflict and asks for the drawings. It cannot see the piping,
so it cannot name the route.

## With `blindflange mcp`

Run with `--mcp-config` pointing at `blindflange mcp --store <copy of gas_plant.rl>`,
and this added to the question:

```
Use the blindflange tools: they hold the plant's piping graph, the valve states and the permits. Report the verdict and the path they give you; do not decide on your own. Also say which listed isolation the route gets around, and how you checked that.
```

The agent made 2 tool calls:

**assess_change** called with:

```json
{
  "permit": {
    "id": "PTW-2201",
    "title": "Restart compression on train B",
    "kind": "operational",
    "operates": [
      {
        "tag": "SDV-110",
        "to": "open"
      },
      {
        "tag": "XV-221",
        "to": "open"
      },
      {
        "tag": "XV-223",
        "to": "open"
      },
      {
        "tag": "FV-222",
        "to": "open"
      }
    ],
    "energises": [
      "K-220"
    ]
  }
}
```

returned (abridged):

```json
{
  "assessment_status": "COMPLETE",
  "conflict_verdict": "BLOCK",
  "evaluation_id": "EVAL-1",
  "first_finding": {
    "code": "PRESSURE_REACHES_TEMPORARY_BARRIER",
    "severity": "BLOCK",
    "certainty": "PROVEN",
    "target": "BF-230",
    "permit": "PTW-1230",
    "path": [
      "V-110",
      "L-110G",
      "SDV-110",
      "L-SUCT",
      "BV-231",
      "L-231",
      "V-230",
      "L-230S",
      "K-230",
      "L-230D",
      "RV-230",
      "L-230R",
      "BF-230"
    ]
  }
}
```
**explain_finding** called with:

```json
{
  "evaluation_id": "EVAL-1",
  "finding": 1
}
```

returned (abridged):

```json
{
  "code": "PRESSURE_REACHES_TEMPORARY_BARRIER",
  "verdict": "BLOCK",
  "certainty": "PROVEN",
  "steps (4 of 13)": [
    {
      "tag": "SDV-110",
      "state": "open",
      "changed_by_request": true,
      "barriers_beside": []
    },
    {
      "tag": "L-SUCT",
      "state": "in_service",
      "changed_by_request": false,
      "barriers_beside": [
        {
          "tag": "BV-211",
          "state": "closed"
        },
        {
          "tag": "BV-221",
          "state": "closed"
        },
        {
          "tag": "XV-211",
          "state": "closed"
        },
        {
          "tag": "XV-231",
          "state": "closed"
        }
      ]
    },
    {
      "tag": "BV-231",
      "state": "open",
      "changed_by_request": false,
      "barriers_beside": []
    },
    {
      "tag": "L-231",
      "state": "in_service",
      "changed_by_request": false,
      "barriers_beside": [
        {
          "tag": "FV-232",
          "state": "closed"
        },
        {
          "tag": "XV-231",
          "state": "closed"
        }
      ]
    }
  ]
}
```

Final answer:

> **DO NOT APPROVE**
> 
> 1. The blindflange `assess_change` check returned **BLOCK** (EVAL-1, status COMPLETE, certainty PROVEN). Opening SDV-110 would let pressure reach BF-230, the temporary blind that PTW-1230 relies on. BF-230 has not been pressure-tested.
> 2. Path: V-110 → L-110G → **SDV-110** (opened by this request) → L-SUCT → **BV-231** → L-231 → V-230 → L-230S → K-230 → L-230D → RV-230 → L-230R → **BF-230**.
> 3. The route gets around **XV-231**, one of PTW-1230's listed isolations. XV-231 is closed, but BV-231 is open beside it. BV-231 is the small-bore train C suction pressurisation bypass, recorded open at 17:20 on 2026-11-15.
> 4. How I checked: I ran `explain_finding` on EVAL-1. It lists XV-231 as closed beside L-SUCT and L-231 but not on the path, and shows BV-231 open and not changed by this request.
> 5. The other permits had no findings. Before restart, BV-231 needs to be closed and the state confirmed, then the check re-run. Otherwise PTW-1230's isolation needs to be re-proven with the shift supervisor.

## What this shows

- The verdict came from the graph. The agent turned the request into tags and passed
  them through; it did not judge the route itself.
- It then used a read-only exploration tool to check the explanation against the
  recorded evaluation, instead of reasoning about piping it cannot see.
- The verdict is recorded in the store as an Evaluation with a snapshot, and
  `blindflange replay` reproduces it.
- Without the tool, a capable model reading the same permits could not find the
  bypass, because the bypass is not in any permit. It is in the piping.

Cost of the two runs: $0.14.
