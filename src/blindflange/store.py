"""The Relate store: open it, build it from YAML, and make the few writes we allow.

Everything the tool knows lives in one .rl file: the plant, the valve states
and the permits. All Cypher is kept in /queries and /schema so it can be read
and run on its own.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

import relate
import yaml

from . import validate
from .model import KINDS, RELATIONS, STATES, label_for

MEMORY = ":memory:"


class StoreError(Exception):
    """A problem with the input or the store that the user can fix."""


class ValidationError(StoreError):
    """A YAML file that is not usable. Carries every problem found."""

    def __init__(self, source: str | Path, problems: list[str]):
        self.source = str(source)
        self.problems = problems
        more = len(problems) - 1
        tail = f" (and {more} more; run 'blindflange validate {self.source}' to list them all)" if more else ""
        super().__init__(f"{self.source}: {problems[0]}{tail}")


def query(name: str) -> str:
    """The text of queries/<name>.cypher, as shipped inside the package."""
    return resources.files("blindflange.queries").joinpath(f"{name}.cypher").read_text(encoding="utf-8")


def schema() -> str:
    return resources.files("blindflange.schema").joinpath("schema.cypher").read_text(encoding="utf-8")


# ---------------------------------------------------------------- opening

def _relate_error(path, e: Exception) -> StoreError:
    text = str(e)
    if "storage locked" in text:
        return StoreError(f"store is open in another process: {path}. Close it and try again.")
    if "not a Relate" in text:
        return StoreError(f"not a Relate store: {path}")
    return StoreError(f"{path}: {text.splitlines()[0] if text else type(e).__name__}")


def connect(path: str | Path = MEMORY, read_only: bool = False, create: bool = False):
    """Open a store. A file must already exist unless create=True."""
    if str(path) != MEMORY:
        p = Path(path)
        if p.is_dir():
            raise StoreError(f"store path is a directory: {path}")
        if not create and not p.exists():
            raise StoreError(f"store not found: {path}")
    try:
        return relate.connect(str(path), read_only=read_only)
    except relate.Error as e:
        raise _relate_error(path, e) from None


@contextmanager
def dry_run(path: str | Path):
    """Open a private copy of a store for a check.

    The check itself is unchanged: write the permit, query, roll back. Working
    on a copy means a check never touches the committed file, because Relate
    rewrites a .rl file whenever a read-write connection closes.
    """
    if not Path(path).is_file():
        raise StoreError(f"store not found: {path}")
    tmp = Path(tempfile.mkdtemp(prefix="blindflange-"))
    try:
        copy = tmp / "check.rl"
        try:
            shutil.copyfile(path, copy)
        except OSError as e:
            raise StoreError(f"cannot read store {path}: {e.strerror or e}") from None
        conn = connect(copy)
        try:
            yield conn
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp(value) -> str:
    """YAML reads an unquoted timestamp as a datetime. Store it as UTC text."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


# ---------------------------------------------------------------- reading YAML

def load_yaml(path: str | Path):
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise StoreError(f"file not found: {path}") from None
    except IsADirectoryError:
        raise StoreError(f"expected a file, got a directory: {path}") from None
    except UnicodeDecodeError:
        raise StoreError(f"{path}: not UTF-8 text") from None
    except OSError as e:
        if p.is_dir():
            raise StoreError(f"expected a file, got a directory: {path}") from None
        raise StoreError(f"cannot read {path}: {e.strerror or e}") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(e, "problem", None) or "not valid YAML"
        raise StoreError(f"{path}: invalid YAML{where}: {problem}") from None


def _checked(path, data, problems):
    if problems:
        raise ValidationError(path, problems)
    return data


def load_plant(path: str | Path) -> dict:
    data = load_yaml(path)
    return _checked(path, data, validate.plant(data))


def load_permit(path: str | Path) -> dict:
    """A permit request. Its tags are checked against the store when it is written."""
    data = load_yaml(path)
    return _checked(path, data, validate.permit(data))


def load_scenario(path: str | Path) -> tuple[dict, dict]:
    """A scenario and its plant, both validated, with permit tags checked against the plant."""
    path = Path(path)
    scenario = load_yaml(path)
    _checked(path, scenario, validate.scenario(scenario))
    plant_path = path.parent / scenario["plant"]
    if not plant_path.is_file():
        raise StoreError(f"{path}: plant file not found: {plant_path}")
    plant = load_plant(plant_path)
    kinds = {c["tag"]: c["kind"] for c in plant["components"]}
    problems = []
    for i, p in enumerate(scenario.get("permits", []), 1):
        problems += validate.permit(p, kinds, in_scenario=True, where=f"permit {i}")
    return _checked(path, scenario, sorted(set(problems), key=problems.index)), plant


# ---------------------------------------------------------------- build

def init_schema(conn) -> None:
    text = "\n".join(l for l in schema().splitlines() if not l.strip().startswith("//"))
    for stmt in (s.strip() for s in text.split(";")):
        if stmt:
            conn.execute(stmt)


def write_plant(conn, plant: dict) -> None:
    """Write a validated plant."""
    by_label: dict[str, list[dict]] = {}
    for c in plant["components"]:
        by_label.setdefault(label_for(c["kind"]), []).append({
            "tag": c["tag"], "kind": c["kind"], "name": c.get("name", c["tag"]),
            "state": c["state"], "normal": c.get("normal", c["state"]),
            "source": bool(c.get("source", False)), "integrity": c.get("integrity"),
        })
    for label, items in by_label.items():
        conn.execute(f"UNWIND $rows AS r CREATE (c:Component:{label}) SET c = r", {"rows": items})
    conn.execute(
        "UNWIND $pairs AS p MATCH (a:Component {tag: p[0]}), (b:Component {tag: p[1]}) "
        "CREATE (a)-[:CONNECTED_TO]->(b)", {"pairs": plant.get("connections", [])})


def _fill(conn, scenario: dict, plant: dict) -> None:
    init_schema(conn)
    write_plant(conn, plant)
    as_of = scenario.get("as_of")
    for permit in scenario.get("permits", []):
        stamp = permit.get("approved_at", as_of)
        with transaction(conn, commit=True):
            write_permit(conn, permit, status=permit.get("status", "active"),
                         approved_at=_timestamp(stamp) if stamp is not None else None, in_scenario=True)


def build(scenario_path: str | Path, out: str | Path = MEMORY):
    """Create a fresh store from a scenario file (a plant plus its active permits).

    In memory, returns a read-write connection. To a file, builds beside the
    target and swaps it in only when complete, then returns a read-only
    connection to the new file.
    """
    scenario, plant = load_scenario(scenario_path)
    if str(out) == MEMORY:
        conn = connect(MEMORY)
        _fill(conn, scenario, plant)
        return conn
    out = Path(out)
    if out.is_dir():
        raise StoreError(f"output path is a directory: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".building.rl")     # Relate uses single-file mode only for .rl
    if tmp.exists():
        tmp.unlink()
    conn = connect(tmp, create=True)
    try:
        _fill(conn, scenario, plant)
    finally:
        conn.close()
    try:
        os.replace(tmp, out)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise StoreError(f"cannot replace {out}: {e.strerror or e}. Is it open in another process?") from None
    return connect(out, read_only=True)


# ---------------------------------------------------------------- writes

def write_permit(conn, permit: dict, status: str, approved_at: str | None = None,
                 in_scenario: bool = False) -> None:
    """Validate a permit against the store, then create it and its edges. Call inside a transaction."""
    problems = validate.permit(permit, in_scenario=in_scenario)
    if problems:
        raise StoreError(problems[0])
    pid = permit["id"]
    if rows(conn, "MATCH (p:Permit {id: $id}) RETURN p.id AS id", id=pid):
        raise StoreError(f"permit {pid} already exists in this store")
    wanted = {t for key in RELATIONS for t in permit.get(key, [])}
    wanted |= {o["tag"] for o in permit.get("operates", [])}
    kinds = {r["tag"]: r["kind"] for r in rows(
        conn, "MATCH (c:Component) WHERE c.tag IN $tags RETURN c.tag AS tag, c.kind AS kind",
        tags=sorted(wanted))}
    problems = validate.permit(permit, kinds, in_scenario=in_scenario)
    if problems:
        raise StoreError(problems[0])
    if status == "active" and approved_at is None:
        approved_at = now()
    conn.execute(
        "CREATE (p:Permit {id: $id, title: $title, kind: $kind, status: $status, "
        "description: $description, approved_at: $at})",
        {"id": pid, "title": permit.get("title", pid), "kind": permit.get("kind", "maintenance"),
         "status": status, "description": permit.get("description", ""),
         "at": approved_at if status == "active" else None})
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
    if comp["kind"] not in KINDS:
        raise StoreError(f"{tag}: kind '{comp['kind']}' is not known to this version")
    allowed = STATES[label_for(comp["kind"])]
    if state not in allowed:
        raise StoreError(f"{tag}: state '{state}' is not valid for a {comp['kind']} "
                         f"(use {', '.join(sorted(allowed))})")
    conn.execute("MATCH (c:Component {tag: $tag}) SET c.state = $state", {"tag": tag, "state": state})
