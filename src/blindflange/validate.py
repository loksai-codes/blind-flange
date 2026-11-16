"""Check plant, scenario and permit YAML before anything is written to a store.

Each function returns a list of problems in plain words. An empty list means
the input is usable. Problems name the item by position and tag so they can be
found in the file.
"""
from __future__ import annotations

from datetime import datetime

from .model import INTEGRITY, KINDS, RELATIONS, STATES

PLANT_KEYS = {"unit", "description", "components", "connections"}
COMPONENT_KEYS = {"tag", "kind", "name", "state", "normal", "source", "integrity"}
SCENARIO_KEYS = {"plant", "description", "as_of", "permits"}
PERMIT_KEYS = {"id", "title", "kind", "description", "works_on", "relies_on", "energises", "operates"}
SCENARIO_PERMIT_KEYS = PERMIT_KEYS | {"status", "approved_at"}
OPERATE_KEYS = {"tag", "to"}


def _choices(values) -> str:
    return ", ".join(sorted(values))


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _unknown_keys(item: dict, allowed: set, where: str) -> list[str]:
    extra = sorted(set(item) - allowed, key=str)
    return [f"{where}: unknown field '{k}' (allowed: {_choices(allowed)})" for k in extra]


def _timestamp(value) -> bool:
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


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
            problems.append(f"{where}: must be a mapping with tag, kind and state")
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
        label = KINDS[kind]
        for key in ("state", "normal"):
            if key not in c:
                if key == "state":
                    problems.append(f"{where}: missing 'state'")
                continue
            if c[key] not in STATES[label]:
                problems.append(f"{where}: {key} '{c[key]}' is not valid for a {kind} "
                                f"(use {_choices(STATES[label])})")
        if "source" in c and not isinstance(c["source"], bool):
            problems.append(f"{where}: 'source' must be true or false")
        if "integrity" in c:
            if label != "Blind":
                problems.append(f"{where}: 'integrity' applies to blinds only")
            elif c["integrity"] not in INTEGRITY:
                problems.append(f"{where}: integrity '{c['integrity']}' is not valid (use {_choices(INTEGRITY)})")
        if "name" in c and not isinstance(c["name"], str):
            problems.append(f"{where}: 'name' must be text")

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
            problems.append(f"{where}: '{key}' must be a list of tags")
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
        if "approved_at" in data and not _timestamp(data["approved_at"]):
            problems.append(f"{where}: 'approved_at' must be a timestamp like 2026-11-15T06:00:00Z")

    if kinds_by_tag is not None:
        unknown = sorted({t for _, t in named if t not in kinds_by_tag})
        if unknown:
            problems.append(f"{where}: unknown tags: {', '.join(unknown)}")
        for tag, to in targets:
            kind = kinds_by_tag.get(tag)
            if kind in KINDS and to not in STATES[KINDS[kind]]:
                problems.append(f"{where}: cannot operate {tag} to '{to}' "
                                f"(a {kind} can be {_choices(STATES[KINDS[kind]])})")
    return problems


def scenario(data) -> list[str]:
    """Check a scenario's own fields and its permits' shape. Tags are checked once the plant is loaded."""
    if not isinstance(data, dict):
        return ["the file must be a mapping with 'plant' and 'permits'"]
    problems = _unknown_keys(data, SCENARIO_KEYS, "scenario")
    if not _text(data.get("plant")):
        problems.append("scenario: missing 'plant' (path to the plant YAML, relative to this file)")
    if "as_of" in data and not _timestamp(data["as_of"]):
        problems.append("scenario: 'as_of' must be a timestamp like 2026-11-15T06:00:00Z")
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
