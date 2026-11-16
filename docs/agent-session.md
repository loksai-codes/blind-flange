# Agent session: can train B be restarted?

Recorded on 16 Nov 2026 with Claude Code 2.1.325 in headless mode (`claude -p`),
model `claude-opus-5-5`, against a copy of `stores/gas_plant.rl`. The same question was
asked twice: once with no tools, and once with `blindflange mcp` connected and
its tools allowed. Nothing below is edited except for line wrapping. The raw
stream-json logs were kept outside the repo.

This is the gate for milestone M2: the agent refuses the restart and quotes the path.

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

No tools were available (`--tools ""`, empty MCP config). The agent had only the
permit list above.

> **DO NOT APPROVE** (not yet; hold pending verification, not a hard reject)
> 
> 1. No direct conflict: none of the valves to be opened (SDV-110, XV-221, XV-223, FV-222) appear in any active permit's isolation list.
> 2. However, XV-221/XV-223 differ by one digit from PTW-1230's isolations XV-231/XV-233 (Train C PSV-230 work). Field-verify the tags so the wrong valves aren't opened on a line with a PSV removed.
> 3. SDV-110 is a low-numbered shutdown valve and may be a common inlet. Confirm it doesn't pressurize headers shared with Train C (PTW-1230, PTW-1610 N2 spool) or F-300.
> 4. Confirm K-220's discharge route. If it feeds dry gas filtration or export, F-300 (PTW-1310) and the open PL-500 door (PTW-1505) would rely only on single XV isolations against compressor pressure.
> 5. Approve once P&IDs and the isolation register confirm Train B is fully segregated from all five active worksites.

It finds no direct conflict and hedges. It cannot see the piping, so it cannot
name the route.

## With `blindflange mcp`

Run with `--mcp-config` pointing at `blindflange mcp --store <copy of gas_plant.rl>`
and an extra instruction: *"Use the blindflange tools: they hold the plant's piping
graph, the valve states and the permits. Report the verdict and the path they give
you; do not decide on your own."*

The agent made 1 tool call:

```json
{
  "tool": "mcp__blindflange__assess_change",
  "arguments": {
    "permit": {
      "id": "PTW-2201",
      "title": "Restart compression on train B",
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
}
```

The tool returned (abridged to the first finding):

```json
{
  "assessment_status": "COMPLETE",
  "conflict_verdict": "BLOCK",
  "evaluation_id": "EVAL-1",
  "revision": 1,
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

Final answer:

> **DO NOT APPROVE**
> 
> - blindflange returned **BLOCK** (assessment COMPLETE, certainty PROVEN, evaluation EVAL-1).
> - The conflict is with PTW-1230 (Train C PSV-230 recertification). Opening SDV-110 would let pressure reach **BF-230**, the temporary blind PTW-1230 relies on, and that blind has not been pressure-tested.
> - Path: V-110 → L-110G → **SDV-110** → L-SUCT → **BV-231** → L-231 → V-230 → L-230S → K-230 → L-230D → RV-230 → L-230R → **BF-230**.
> - The pressure gets into train C through BV-231, not through XV-231 or XV-233, which are PTW-1230's listed isolations. So that permit's isolation set doesn't cover this route.
> - Possible sources include V-110, K-220, V-100, V-120, WH-MAN, the export line (L-EXP) and others. Before PTW-2201 goes ahead, BV-231 needs to be confirmed closed and added as an isolation, or PTW-1230 needs to be closed out; then run the check again.

## What this shows

- The verdict came from the graph. The agent turned the request into tags and passed
  them through. It did not judge the route itself.
- The tool's answer is recorded in the store as `EVAL-1`, with a snapshot,
  and `blindflange replay EVAL-1` reproduces it.
- Without the tool, a capable model reading the same permits could not find the
  bypass, because the bypass is not in any permit. It is in the piping.

Model output varies from run to run. The tool's result does not: it is a graph query
over a recorded snapshot.
