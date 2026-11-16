"""Check plant, scenario, permit and state-change input before anything is written.

Each function returns a list of problems in plain words. An empty list means
the input is usable. Problems name the item by position and tag so they can be
found in the file.
"""
from __future__ import annotations

from datetime import datetime

from .model import INTEGRITY, KINDS, MAX_HOPS_LIMIT, RELATIONS, STATES, UNKNOWN

PLANT_KEYS = {"unit", "description", "components", "connections"}
COMPONENT_KEYS = {"tag", "kind", "name", "state", "normal", "pressure_source", "integrity",
                  "observed_at", "observed_by"}
SCENARIO_KEYS = {"plant", "description", "as_of", "max_observation_age_hours", "observations", "permits"}
OBSERVATION_KEYS = {"tag", "state", "observed_at", "observed_by"}
PERMIT_KEYS = {"id", "title", "kind", "description", "works_on", "relies_on", "energises", "operates"}
SCENARIO_PERMIT_KEYS = PERMIT_KEYS | {"status", "approved_at"}
OPERATE_KEYS = {"tag", "to"}

AMBIGUOUS_BLIND = ("'removed' is ambiguous for a blind (the blind, or the spool it closes?). "
                   "Use installed or not_installed")


def _choices(values) -> str:
    return ", ".join(sorted(values))


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _unknown_keys(item: dict, allowed: set, where: str) -> list[str]:
    extra = sorted(set(item) - allowed, key=str)
    out = []
    for k in extra:
        hint = " ('source' is now 'pressure_source')" if k == "source" else ""
        out.append(f"{where}: unknown field '{k}'{hint} (allowed: {_choices(allowed)})")
    return out


def is_timestamp(value) -> bool:
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def state_problem(kind: str | None, state, where: str, allow_unknown: bool = True) -> str | None:
    """Why `state` is not valid for a component of `kind`, or None if it is."""
    if kind not in KINDS:
        return None                                     # reported elsewhere
    label = KINDS[kind]
    if label == "Blind" and state == "removed":
        return f"{where}: {AMBIGUOUS_BLIND}"
    allowed = STATES[label] if allow_unknown else STATES[label] - {UNKNOWN}
    if state not in allowed:
        return f"{where}: state '{state}' is not valid for a {kind} (use {_choices(allowed)})"
    return None


def plant(data) -> list[str]:
    if not isinstance(data, dict):
        return ["the file must be a mapping with 'components' and 'connections'"]
    problems = _unknown_keys(data, PLANT_KEYS, "plant")
    comps = data.get("components")
    if not isinstance(comps, list) or not comps:
        return problems + ["'components' must be a non-empty list"]

    seen: dict[str, int] = {}
    for i, c in enumerate(comps, 1):
        where = f"component {i}"
        if not isinstance(c, dict):
            problems.append(f"{where}: must be a mapping with tag and kind")
            continue
        tag = c.get("tag")
        if not _text(tag):
            problems.append(f"{where}: missing 'tag'")
            continue
        where = f"component {i} ({tag})"
        if tag in seen:
            problems.append(f"{where}: duplicate tag, first used by component {seen[tag]}")
        else:
            seen[tag] = i
        problems += _unknown_keys(c, COMPONENT_KEYS, where)
        kind = c.get("kind")
        if kind is None:
            problems.append(f"{where}: missing 'kind'")
            continue
        if kind not in KINDS:
            problems.append(f"{where}: unknown kind '{kind}' (use {_choices(KINDS)})")
            continue
        for key in ("state", "normal"):
            if key in c:
                p = state_problem(kind, c[key], f"{where} {key}")
                if p:
                    problems.append(p)
        if "pressure_source" in c and not isinstance(c["pressure_source"], bool):
            problems.append(f"{where}: 'pressure_source' must be true or false")
        if "integrity" in c:
            if KINDS[kind] != "Blind":
                problems.append(f"{where}: 'integrity' applies to blinds only")
            elif c["integrity"] not in INTEGRITY:
                problems.append(f"{where}: integrity '{c['integrity']}' is not valid (use {_choices(INTEGRITY)})")
        if "name" in c and not isinstance(c["name"], str):
            problems.append(f"{where}: 'name' must be text")
        if "observed_at" in c and not is_timestamp(c["observed_at"]):
            problems.append(f"{where}: 'observed_at' must be a timestamp like 2026-11-15T06:00:00Z")
        if "observed_by" in c and not _text(c["observed_by"]):
            problems.append(f"{where}: 'observed_by' must be text")

    conns = data.get("connections", [])
    if not isinstance(conns, list):
        return problems + ["'connections' must be a list of [tag, tag] pairs"]
    pairs: dict[frozenset, int] = {}
    for i, pair in enumerate(conns, 1):
        where = f"connection {i}"
        if not (isinstance(pair, list) and len(pair) == 2 and all(_text(t) for t in pair)):
            problems.append(f"{where}: must be a pair of tags like [P-A, L-PD-A], got {pair!r}")
            continue
        a, b = pair
        where = f"connection {i} [{a}, {b}]"
        for t in (a, b):
            if t not in seen:
                problems.append(f"{where}: unknown tag '{t}'")
        if a == b:
            problems.append(f"{where}: connects a tag to itself")
            continue
        key = frozenset(pair)
        if key in pairs:
            problems.append(f"{where}: duplicate of connection {pairs[key]}")
        else:
            pairs[key] = i
    return problems


def permit(data, kinds_by_tag: dict[str, str] | None = None, in_scenario: bool = False,
           where: str = "permit") -> list[str]:
    """Check a permit's shape. With kinds_by_tag, also check its tags and target states."""
    if not isinstance(data, dict):
        return [f"{where}: must be a mapping with at least an 'id'"]
    pid = data.get("id")
    if not _text(pid):
        return [f"{where}: missing 'id'"]
    where = f"{where} {pid}" if where != "permit" else f"permit {pid}"
    problems = _unknown_keys(data, SCENARIO_PERMIT_KEYS if in_scenario else PERMIT_KEYS, where)
    for key in ("title", "kind", "description"):
        if key in data and not isinstance(data[key], str):
            problems.append(f"{where}: '{key}' must be text")

    named: list[tuple[str, str]] = []                  # (field, tag)
    for key in RELATIONS:
        tags = data.get(key, [])
        if not (isinstance(tags, list) and all(_text(t) for t in tags)):
            problems.append(f"{where}: '{key}' must be a list of tags, like [P-A]")
            continue
        named += [(key, t) for t in tags]

    ops = data.get("operates", [])
    targets: list[tuple[str, str]] = []                # (tag, to)
    if not isinstance(ops, list):
        problems.append(f"{where}: 'operates' must be a list of {{tag, to}} items")
        ops = []
    for i, op in enumerate(ops, 1):
        w = f"{where} operates {i}"
        if not isinstance(op, dict) or not _text(op.get("tag")) or not _text(op.get("to")):
            problems.append(f"{w}: needs 'tag' and 'to', like {{tag: SV-A, to: open}}")
            continue
        problems += _unknown_keys(op, OPERATE_KEYS, w)
        named.append(("operates", op["tag"]))
        targets.append((op["tag"], op["to"]))
    seen_ops = [t for t, _ in targets]
    for t in sorted({t for t in seen_ops if seen_ops.count(t) > 1}):
        problems.append(f"{where}: operates {t} more than once")

    if in_scenario:
        if data.get("status", "active") not in {"active", "requested"}:
            problems.append(f"{where}: status '{data['status']}' is not valid here (use active, requested)")
        if "approved_at" in data and not is_timestamp(data["approved_at"]):
            problems.append(f"{where}: 'approved_at' must be a timestamp like 2026-11-15T06:00:00Z")

    if kinds_by_tag is not None:
        unknown = sorted({t for _, t in named if t not in kinds_by_tag})
        if unknown:
            problems.append(f"{where}: unknown tags: {', '.join(unknown)}")
        for tag, to in targets:
            if tag in kinds_by_tag:
                p = state_problem(kinds_by_tag[tag], to, f"{where} operates {tag}", allow_unknown=False)
                if p:
                    problems.append(p)
    return problems


def changes(items, kinds_by_tag: dict[str, str] | None = None, where: str = "change") -> list[str]:
    """Check a list of state changes [{tag, to}] (a `set` or a what-if)."""
    if not isinstance(items, list) or not items:
        return [f"{where}: give at least one change, like RLV-504=closed"]
    problems = []
    seen = set()
    for i, c in enumerate(items, 1):
        w = f"{where} {i}"
        if not isinstance(c, dict) or not _text(c.get("tag")) or not _text(c.get("to")):
            problems.append(f"{w}: needs a tag and a state, like RLV-504=closed")
            continue
        if c["tag"] in seen:
            problems.append(f"{w}: {c['tag']} is changed more than once")
        seen.add(c["tag"])
        if kinds_by_tag is not None:
            if c["tag"] not in kinds_by_tag:
                problems.append(f"{w}: unknown tag {c['tag']}")
            else:
                p = state_problem(kinds_by_tag[c["tag"]], c["to"], f"{w} ({c['tag']})")
                if p:
                    problems.append(p)
    return problems


def observation(by, observed_at=None) -> list[str]:
    """Check who made an observation and, if given, when."""
    problems = []
    if not _text(by):
        problems.append("an observation needs an observer: give --by with a name")
    if observed_at is not None and not is_timestamp(observed_at):
        problems.append(f"observed_at must be a timestamp like 2026-11-15T06:00:00Z, got {observed_at!r}")
    return problems


def max_hops(value) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HOPS_LIMIT:
        return [f"max_hops must be a whole number from 1 to {MAX_HOPS_LIMIT}, got {value!r}"]
    return []


def scenario(data) -> list[str]:
    """Check a scenario's own fields and its permits' shape. Tags are checked once the plant is loaded."""
    if not isinstance(data, dict):
        return ["the file must be a mapping with 'plant', 'as_of' and 'permits'"]
    problems = _unknown_keys(data, SCENARIO_KEYS, "scenario")
    if not _text(data.get("plant")):
        problems.append("scenario: missing 'plant' (path to the plant YAML, relative to this file)")
    if "as_of" not in data:
        problems.append("scenario: missing 'as_of' (the time of this picture, like 2026-11-15T06:00:00Z)")
    elif not is_timestamp(data["as_of"]):
        problems.append("scenario: 'as_of' must be a timestamp like 2026-11-15T06:00:00Z")
    age = data.get("max_observation_age_hours", 12)
    if isinstance(age, bool) or not isinstance(age, (int, float)) or age <= 0:
        problems.append("scenario: 'max_observation_age_hours' must be a positive number")
    obs = data.get("observations", [])
    if not isinstance(obs, list):
        problems.append("scenario: 'observations' must be a list")
        obs = []
    for i, o in enumerate(obs, 1):
        w = f"observation {i}"
        if not isinstance(o, dict) or not _text(o.get("tag")) or "state" not in o:
            problems.append(f"{w}: needs 'tag' and 'state'")
            continue
        problems += _unknown_keys(o, OBSERVATION_KEYS, w)
        if "observed_at" in o and not is_timestamp(o["observed_at"]):
            problems.append(f"{w}: 'observed_at' must be a timestamp")
        if "observed_by" in o and not _text(o["observed_by"]):
            problems.append(f"{w}: 'observed_by' must be text naming the observer")
    permits = data.get("permits", [])
    if not isinstance(permits, list):
        return problems + ["scenario: 'permits' must be a list"]
    seen: set[str] = set()
    for i, p in enumerate(permits, 1):
        problems += permit(p, in_scenario=True, where=f"permit {i}")
        pid = p.get("id") if isinstance(p, dict) else None
        if _text(pid):
            if pid in seen:
                problems.append(f"permit {i} {pid}: duplicate permit id")
            seen.add(pid)
    return problems
