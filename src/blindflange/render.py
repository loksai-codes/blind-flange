"""Plain-text output for a result. Shapes data only; decides nothing."""
from __future__ import annotations

from . import checks

ARROW = " -> "


def result_text(r: checks.Result) -> str:
    out = []
    req = r.request
    label = f"{req['id']}  {req['title']}" if req.get("id") else req.get("title", "")
    out.append(f"{r.verdict:<10} {label}")
    out.append(f"  assessment_status: {r.assessment_status}    conflict_verdict: {r.conflict_verdict or 'none'}"
               + (f"    revision {r.revision}" if r.revision is not None else "")
               + (f"    {r.evaluation_id}" if r.evaluation_id else ""))
    if r.assessed_at:
        out.append(f"  assessed at {r.assessed_at} ({r.mode or 'snapshot'} store)")
    if r.hypothetical:
        out.append("  What-if: " + ", ".join(f"{h['tag']}={h['to']}" for h in r.hypothetical)
                   + " (not applied to the store)")
    if r.error:
        out.append(f"\n  Not assessed: {r.error}")
        return "\n".join(out)

    for i, f in enumerate(r.findings, 1):
        tag = f"[{f.severity}]"
        extra = [] if f.origin == checks.INTRODUCED else ["existing"]
        if f.certainty == checks.POSSIBLE:
            extra.append("possible")
        out.append(f"\n  {i}. {tag} {f.code}" + (f"  ({', '.join(extra)})" if extra else ""))
        out.append(f"     {f.message}")
        if f.permit:
            out.append(f"     Other permit: {f.permit}  {f.permit_title or ''}".rstrip())
        if len(f.path) > 1:
            n = len(f.path) - 1
            out.append(f"     Path ({n} hop{'s' if n != 1 else ''}): {ARROW.join(f.path)}")
            others = [s for s in f.sources if s != f.path[0]]
            if others:
                more = f" and {len(others) - 3} more" if len(others) > 3 else ""
                out.append(f"     Also reached from: {', '.join(others[:3])}{more}")
            if f.possible_sources:
                out.append(f"     Possibly also from: {', '.join(f.possible_sources[:3])}"
                           f"{' and more' if len(f.possible_sources) > 3 else ''} "
                           f"(only by an unconfirmed route or against declared flow)")
            if f.other_service_sources:
                n = len(f.other_service_sources)
                out.append(f"     Not listed: {n} source{'s' if n != 1 else ''} in other services with no "
                           f"declared tie-in (--json shows them)")
        for e in f.evidence:
            out.append(f"     Evidence: {e}")
        if f.uncertain:
            out.append(f"     Unconfirmed: {', '.join(f.uncertain)}")
        if f.against_flow:
            out.append(f"     Against declared flow: {', '.join(f.against_flow)}")

    if not r.findings:
        if r.assessment_status == checks.COMPLETE:
            out.append("\n  No conflicts found with active permits or current plant state.")
        else:
            out.append("\n  No conflict established, but the assessment is incomplete.")
    for reason in r.incomplete_reasons:
        if "search stopped" in reason:
            out.append(f"\n  Incomplete: {reason}.")
    other = [u for u in r.unknowns if not u.get("relevant")]
    if other:
        out.append("\n  Unconfirmed elsewhere (not on any route that matters here): "
                   + ", ".join(f"{u['tag']} ({u['reason']})" for u in other))
    if r.request.get("type") == "permit":
        if r.baseline_shared_tags:
            pairs = "; ".join(f"{p}: {', '.join(t)}" for p, t in r.baseline_shared_tags.items())
            out.append(f"\n  Tag matching alone: shared tags with {pairs}.")
        else:
            out.append("\n  Tag matching alone: no shared tags with any active permit, so it would pass.")
    return "\n".join(out)
