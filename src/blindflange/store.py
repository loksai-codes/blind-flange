"""The Relate store: open it, build it from YAML, and make the few writes we allow.

Everything the tool knows lives in one .rl file: the plant, the valve states
and the permits. All Cypher is kept in /queries and /schema so it can be read
and run on its own.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import relate
import yaml

ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "queries"
SCHEMA = ROOT / "schema" / "schema.cypher"

LABELS = {"valve": "Valve", "check_valve": "Valve", "psv": "Valve", "blind": "Blind", "line": "Line"}
STATES = {
    "Valve": {"open", "closed", "removed"},
    "Blind": {"installed", "removed"},
    "Line": {"in_service", "removed"},
    "Equipment": {"in_service", "shutdown", "removed"},
}
RELATIONS = {"works_on": "WORKS_ON", "relies_on": "RELIES_ON", "energises": "ENERGISES"}


class StoreError(Exception):
    """A problem with the input or the store that the user can fix."""


def query(name: str) -> str:
    return (QUERIES / f"{name}.cypher").read_text(encoding="utf-8")


def connect(path: str | Path = ":memory:", read_only: bool = False):
    if str(path) != ":memory:" and read_only and not Path(path).exists():
        raise StoreError(f"store not found: {path}")
    return relate.connect(str(path), read_only=read_only)


def rows(conn, cypher: str, **params) -> list[dict]:
    return conn.execute(cypher, params).data()


@contextmanager
def transaction(conn, commit: bool):
    """Run a block in one transaction. With commit=False it is a dry run."""
    conn.autocommit = False
    try:
        yield
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def label_for(kind: str) -> str:
    return LABELS.get(kind, "Equipment")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_yaml(path: str | Path) -> dict:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise StoreError(f"file not found: {path}") from None


# ---------------------------------------------------------------- build

def init_schema(conn) -> None:
    text = "\n".join(l for l in SCHEMA.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("//"))
    for stmt in (s.strip() for s in text.split(";")):
        if stmt:
            conn.execute(stmt)


def load_plant(conn, plant: dict) -> None:
    comps = plant.get("components", [])
    tags = [c["tag"] for c in comps]
    if len(tags) != len(set(tags)):
        raise StoreError("duplicate component tags in plant file")
    by_label: dict[str, list[dict]] = {}
    for c in comps:
        label = label_for(c["kind"])
        if c["state"] not in STATES[label]:
            raise StoreError(f"{c['tag']}: state '{c['state']}' is not valid for {label}")
        by_label.setdefault(label, []).append({
            "tag": c["tag"], "kind": c["kind"], "name": c.get("name", c["tag"]),
            "state": c["state"], "normal": c.get("normal", c["state"]),
            "source": bool(c.get("source", False)), "integrity": c.get("integrity"),
        })
    for label, items in by_label.items():
        conn.execute(
            f"UNWIND $rows AS r CREATE (c:Component:{label}) SET c = r", {"rows": items})
    known = set(tags)
    pairs = []
    for a, b in plant.get("connections", []):
        if a not in known or b not in known:
            raise StoreError(f"connection [{a}, {b}] names an unknown tag")
        pairs.append([a, b])
    conn.execute(
        "UNWIND $pairs AS p MATCH (a:Component {tag: p[0]}), (b:Component {tag: p[1]}) "
        "CREATE (a)-[:CONNECTED_TO]->(b)", {"pairs": pairs})


def build(scenario_path: str | Path, out: str | Path = ":memory:"):
    """Create a fresh store from a scenario file (a plant plus its active permits)."""
    scenario_path = Path(scenario_path)
    scenario = load_yaml(scenario_path)
    if str(out) != ":memory:":
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
    conn = connect(out)
    init_schema(conn)
    load_plant(conn, load_yaml(scenario_path.parent / scenario["plant"]))
    for permit in scenario.get("permits", []):
        with transaction(conn, commit=True):
            write_permit(conn, permit, status=permit.get("status", "active"))
    return conn


# ---------------------------------------------------------------- writes

def write_permit(conn, permit: dict, status: str) -> None:
    """Create a permit and its edges. Call inside a transaction."""
    pid = permit.get("id")
    if not pid:
        raise StoreError("permit has no id")
    if rows(conn, "MATCH (p:Permit {id: $id}) RETURN p.id AS id", id=pid):
        raise StoreError(f"permit {pid} already exists in this store")
    wanted = {t for key in RELATIONS for t in permit.get(key, [])}
    wanted |= {o["tag"] for o in permit.get("operates", [])}
    found = {r["tag"] for r in rows(
        conn, "MATCH (c:Component) WHERE c.tag IN $tags RETURN c.tag AS tag", tags=sorted(wanted))}
    if wanted - found:
        raise StoreError(f"permit {pid} names unknown tags: {', '.join(sorted(wanted - found))}")
    conn.execute(
        "CREATE (p:Permit {id: $id, title: $title, kind: $kind, status: $status, "
        "description: $description, approved_at: $at})",
        {"id": pid, "title": permit.get("title", pid), "kind": permit.get("kind", "maintenance"),
         "status": status, "description": permit.get("description", ""),
         "at": now() if status == "active" else None})
    for key, rel in RELATIONS.items():
        if permit.get(key):
            conn.execute(
                f"MATCH (p:Permit {{id: $id}}), (c:Component) WHERE c.tag IN $tags "
                f"CREATE (p)-[:{rel}]->(c)", {"id": pid, "tags": permit[key]})
    for op in permit.get("operates", []):
        conn.execute(
            "MATCH (p:Permit {id: $id}), (c:Component {tag: $tag}) CREATE (p)-[:OPERATES {to: $to}]->(c)",
            {"id": pid, "tag": op["tag"], "to": op["to"]})


def activate(conn, pid: str) -> None:
    """Approve a requested permit: mark it active and apply its state changes."""
    conn.execute("MATCH (p:Permit {id: $id}) SET p.status = 'active', p.approved_at = $at",
                 {"id": pid, "at": now()})
    conn.execute("MATCH (:Permit {id: $id})-[o:OPERATES]->(c:Component) SET c.state = o.to", {"id": pid})
    conn.execute("MATCH (:Permit {id: $id})-[:ENERGISES]->(c:Component) SET c.state = 'in_service'",
                 {"id": pid})


def close_permit(conn, pid: str) -> list[dict]:
    """Close a permit. Returns isolation points other active permits still need."""
    if not rows(conn, "MATCH (p:Permit {id: $id, status: 'active'}) RETURN p.id AS id", id=pid):
        raise StoreError(f"no active permit {pid}")
    still = rows(conn,
                 "MATCH (:Permit {id: $id})-[:RELIES_ON]->(v:Component)<-[:RELIES_ON]-(q:Permit {status: 'active'}) "
                 "WHERE q.id <> $id RETURN v.tag AS tag, collect(q.id) AS permits ORDER BY tag", id=pid)
    conn.execute("MATCH (p:Permit {id: $id}) SET p.status = 'closed', p.closed_at = $at",
                 {"id": pid, "at": now()})
    return still


def component(conn, tag: str) -> dict:
    found = rows(conn, "MATCH (c:Component {tag: $tag}) "
                       "RETURN c.tag AS tag, c.kind AS kind, c.name AS name, c.state AS state", tag=tag)
    if not found:
        raise StoreError(f"unknown tag: {tag}")
    return found[0]


def set_state(conn, tag: str, state: str) -> None:
    comp = component(conn, tag)
    label = label_for(comp["kind"])
    if state not in STATES[label]:
        raise StoreError(f"{tag}: state '{state}' is not valid for {label} "
                         f"(use {', '.join(sorted(STATES[label]))})")
    conn.execute("MATCH (c:Component {tag: $tag}) SET c.state = $state", {"tag": tag, "state": state})
