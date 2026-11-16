"""The Relate store: open it, build it from YAML, and make the few writes we allow.

Everything the tool knows lives in one .rl file: the plant, the observed states,
the permits, a revision number and a record of every evaluation. All Cypher is
kept in /queries and /schema so it can be read and run on its own.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path

import relate
import yaml

from . import validate
from .model import DEFAULT_MAX_AGE_HOURS, DEFAULT_MAX_HOPS, KINDS, LABELS, MAX_HOPS_LIMIT, RELATIONS, label_for

MEMORY = ":memory:"


class StoreError(Exception):
    """A problem with the input or the store that the user can fix."""


class ValidationError(StoreError):
    """An input that is not usable. Carries every problem found."""

    def __init__(self, source: str | Path, problems: list[str]):
        self.source = str(source)
        self.problems = problems
        more = len(problems) - 1
        tail = f" (and {more} more; run 'blindflange validate {self.source}' to list them all)" if more else ""
        super().__init__(f"{self.source}: {problems[0]}{tail}")


class StaleRevisionError(StoreError):
    """The request was prepared against an older state of the store."""


# ---------------------------------------------------------------- queries

def _read(package: str, name: str) -> str:
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def query(name: str, max_hops: int | None = None) -> str:
    """The text of queries/<name>.cypher, as shipped inside the package.

    Relate accepts only a literal path bound, so __MAX_HOPS__ and __PROBE_HOPS__
    are replaced with validated integers. Nothing else is ever put into query text.
    """
    text = _read("blindflange.queries", f"{name}.cypher")
    if "__MAX_HOPS__" in text:
        hops = DEFAULT_MAX_HOPS if max_hops is None else max_hops
        if validate.max_hops(hops):
            raise StoreError(validate.max_hops(hops)[0])
        text = text.replace("__PROBE_HOPS__", str(int(hops) + 1)).replace("__MAX_HOPS__", str(int(hops)))
    return text


def schema() -> str:
    return _read("blindflange.schema", "schema.cypher")


@lru_cache(maxsize=None)
def _named() -> dict[str, str]:
    """Named statements from queries/store.cypher (each starts with `// :name`)."""
    out: dict[str, str] = {}
    current = None
    for line in query("store").splitlines():
        m = re.match(r"^// :(\w+)\s*$", line)
        if m:
            current = m.group(1)
            out[current] = ""
        elif current and not line.lstrip().startswith("//"):
            out[current] += line + "\n"
    return {k: v.strip() for k, v in out.items()}


def statements(text: str) -> list[str]:
    """Split a query file into statements on ';', dropping comment lines."""
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))
    return [s.strip() for s in body.split(";") if s.strip()]


def rows(conn, cypher: str, **params) -> list[dict]:
    return conn.execute(cypher, params).data()


def run(conn, name: str, **params) -> list[dict]:
    """Run a named statement from queries/store.cypher."""
    return rows(conn, _named()[name], **params)


# ---------------------------------------------------------------- time

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp(value) -> str:
    """Any accepted timestamp as UTC text 'YYYY-MM-DDTHH:MM:SSZ', so text order is time order."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise StoreError(f"not a timestamp: {value!r} (use a time like 2026-11-15T06:00:00Z)") from None
    if not isinstance(value, datetime):
        raise StoreError(f"not a timestamp: {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_before(ts: str, hours: float) -> str:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00")) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- opening

def _relate_error(path, e: Exception) -> StoreError:
    text = str(e)
    if "storage locked" in text or "locked" in text.lower():
        return StoreError(f"store is open in another process: {path}. Close it and try again.")
    if "not a Relate" in text:
        return StoreError(f"not a Relate store: {path}")
    return StoreError(f"{path}: {text.splitlines()[0] if text else type(e).__name__}")


def connect(path: str | Path = MEMORY, read_only: bool = False, create: bool = False):
    """Open a store. A file must already exist unless create=True.

    Relate allows one connection per file at a time, so every write in this tool
    goes through a single connection: this is the one writer.
    """
    if str(path) != MEMORY:
        p = Path(path)
        if p.is_dir():
            raise StoreError(f"store path is a directory: {path}")
        if p.suffix != ".rl":
            raise StoreError(f"store files end in .rl: {path}")
        if not create and not p.exists():
            raise StoreError(f"store not found: {path}")
    try:
        conn = relate.connect(str(path), read_only=read_only)
    except relate.Error as e:
        raise _relate_error(path, e) from None
    if not create and str(path) != MEMORY and not run(conn, "store_info"):
        conn.close()
        raise StoreError(f"{path} was not built by this version of blindflange (no Store node). "
                         f"Rebuild it with 'blindflange build'.")
    return conn


@contextmanager
def scratch_copy(path: str | Path):
    """A read-write connection to a temporary copy of a store, deleted afterwards.

    For reads that need a rolled-back transaction (the handover survey). Relate
    rewrites a .rl file whenever a read-write connection closes, even after a
    rollback, so working on a copy leaves the real file's bytes untouched.
    """
    connect(path, read_only=True).close()                 # same checks and errors as opening it
    tmp = Path(tempfile.mkdtemp(prefix="blindflange-"))
    try:
        copy = tmp / "copy.rl"
        shutil.copyfile(path, copy)
        conn = connect(copy)
        try:
            yield conn
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


@contextmanager
def write(conn, expect_revision: int | None = None):
    """One committed change to plant state or permits.

    Checks the revision the caller saw (if given), applies the block, bumps the
    revision and commits, all in one transaction. A request prepared against an
    older revision is refused, so a decision is never applied to a plant that
    changed after it was checked.
    """
    with transaction(conn, commit=True):
        current = info(conn)["revision"]
        if expect_revision is not None and expect_revision != current:
            raise StaleRevisionError(
                f"stale revision: this request was prepared against revision {expect_revision}, "
                f"but the store is at revision {current}. Check it again.")
        yield current
        run(conn, "store_bump")


def info(conn) -> dict:
    got = run(conn, "store_info")
    if not got:
        raise StoreError("this store has no Store node; rebuild it with 'blindflange build'")
    return got[0]


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
    """A permit request. Its tags are checked against the store when it is assessed."""
    data = load_yaml(path)
    return _checked(path, data, validate.permit(data))


def load_scenario(path: str | Path) -> tuple[dict, dict]:
    """A scenario and its plant, both validated, with permit and observation tags checked."""
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
    for i, o in enumerate(scenario.get("observations", []), 1):
        if o["tag"] not in kinds:
            problems.append(f"observation {i}: unknown tag {o['tag']}")
        else:
            p = validate.state_problem(kinds[o["tag"]], o["state"], f"observation {i} ({o['tag']})")
            if p:
                problems.append(p)
    return _checked(path, scenario, sorted(set(problems), key=problems.index)), plant


# ---------------------------------------------------------------- build

def init_schema(conn) -> None:
    for stmt in statements(schema()):
        conn.execute(stmt)


def _component_rows(components: list[dict], as_of: str) -> list[dict]:
    out = []
    for c in components:
        has_state = c.get("state") is not None
        props = {
            "tag": c["tag"], "kind": c["kind"], "name": c.get("name") or c["tag"],
            "state": c.get("state"), "normal": c.get("normal", c.get("state")),
            "pressure_source": bool(c.get("pressure_source", False)), "integrity": c.get("integrity"),
            "service": c.get("service") or "process",
            "observed_at": timestamp(c["observed_at"]) if c.get("observed_at") else (as_of if has_state else None),
            "observed_by": c.get("observed_by") or ("scenario" if has_state else None),
            "planned_state": c.get("planned_state"), "planned_by": c.get("planned_by"),
            "planned_at": c.get("planned_at"),
        }
        out.append({"label": label_for(c["kind"]), "props": {k: v for k, v in props.items() if v is not None}})
    return out


def _load(conn, components: list[dict], connections: list, as_of: str, max_age_hours: float, plant: str,
          revision: int = 1, tie_ins: list | None = None) -> None:
    init_schema(conn)
    run(conn, "store_create", as_of=as_of, max_age_hours=max_age_hours, plant=plant, revision=revision,
        tie_ins=[f"{a}>{b}" for a, b in (tie_ins or [])])
    comp_rows = _component_rows(components, as_of)
    for label in LABELS:
        run(conn, f"load_{label.lower()}", rows=comp_rows)
    run(conn, "load_connections", pairs=[list(p) for p in connections])


def _fill(conn, scenario: dict, plant: dict, plant_name: str) -> None:
    as_of = timestamp(scenario["as_of"])
    comps = {c["tag"]: dict(c) for c in plant["components"]}
    for o in scenario.get("observations", []):
        c = comps[o["tag"]]
        c["state"] = o["state"]
        c["observed_at"] = o.get("observed_at", as_of)
        c["observed_by"] = o.get("observed_by", "scenario")
    _load(conn, list(comps.values()), plant.get("connections", []), as_of,
          scenario.get("max_observation_age_hours", DEFAULT_MAX_AGE_HOURS), plant_name,
          tie_ins=plant.get("tie_ins", []))
    for permit in scenario.get("permits", []):
        stamp = timestamp(permit.get("approved_at", as_of))
        with transaction(conn, commit=True):
            write_permit(conn, permit, status=permit.get("status", "active"), approved_at=stamp, in_scenario=True)


def build(scenario_path: str | Path, out: str | Path = MEMORY):
    """Create a fresh store from a scenario file (a plant plus its active permits).

    In memory, returns a read-write connection. To a file, builds beside the
    target and swaps it in only when complete, then returns a read-only
    connection to the new file. The same scenario always gives the same graph.
    """
    scenario, plant = load_scenario(scenario_path)
    plant_name = plant.get("unit") or Path(scenario["plant"]).stem
    if str(out) == MEMORY:
        conn = connect(MEMORY)
        _fill(conn, scenario, plant, plant_name)
        return conn
    out = Path(out)
    if out.is_dir():
        raise StoreError(f"output path is a directory: {out}")
    if out.suffix != ".rl":
        raise StoreError(f"store files end in .rl: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".building.rl")     # Relate uses single-file mode only for .rl
    if tmp.exists():
        tmp.unlink()
    conn = connect(tmp, create=True)
    try:
        _fill(conn, scenario, plant, plant_name)
    finally:
        conn.close()
    try:
        os.replace(tmp, out)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise StoreError(f"cannot replace {out}: {e.strerror or e}. Is it open in another process?") from None
    return connect(out, read_only=True)


# ---------------------------------------------------------------- snapshots

def snapshot(conn) -> dict:
    """Every input an assessment reads, as plain data, so it can be replayed later."""
    s = info(conn)
    comps = []
    for c in run(conn, "snapshot_components"):
        comps.append({k: v for k, v in c.items() if v is not None})
    return {
        "store": {"revision": s["revision"], "as_of": s["as_of"], "max_age_hours": s["max_age_hours"],
                  "plant": s["plant"], "tie_ins": [t.split(">", 1) for t in s["tie_ins"]]},
        "components": comps,
        "connections": [[r["a"], r["b"]] for r in run(conn, "snapshot_connections")],
        "permits": [{k: v for k, v in p.items() if v not in (None, [])} for p in run(conn, "snapshot_permits")],
    }


def from_snapshot(snap: dict):
    """An in-memory store holding exactly what a snapshot recorded."""
    conn = connect(MEMORY)
    st = snap["store"]
    _load(conn, snap["components"], snap["connections"], st["as_of"], st["max_age_hours"], st["plant"],
          revision=st["revision"], tie_ins=st.get("tie_ins", []))
    for p in snap["permits"]:
        with transaction(conn, commit=True):
            write_permit(conn, p, status="active", approved_at=p.get("approved_at"), in_scenario=True,
                         validate_input=False)
    return conn


# ---------------------------------------------------------------- writes

def kinds_for(conn, tags) -> dict[str, str]:
    return {r["tag"]: r["kind"] for r in run(conn, "component_kinds", tags=sorted(set(tags)))}


def write_permit(conn, permit: dict, status: str, approved_at: str | None = None,
                 in_scenario: bool = False, validate_input: bool = True) -> None:
    """Validate a permit against the store, then create it and its edges. Call inside a transaction."""
    if validate_input:
        problems = validate.permit(permit, in_scenario=in_scenario)
        if problems:
            raise ValidationError("request", problems)
    pid = permit["id"]
    if run(conn, "permit_exists", id=pid):
        raise StoreError(f"permit {pid} already exists in this store")
    if validate_input:
        wanted = {t for key in RELATIONS for t in permit.get(key, [])}
        wanted |= {o["tag"] for o in permit.get("operates", [])}
        problems = validate.permit(permit, kinds_for(conn, wanted), in_scenario=in_scenario)
        if problems:
            raise ValidationError("request", problems)
    run(conn, "permit_create", id=pid, title=permit.get("title", pid), kind=permit.get("kind", "maintenance"),
        status=status, description=permit.get("description", ""),
        approved_at=approved_at if status == "active" else None)
    for key, rel in RELATIONS.items():
        if permit.get(key):
            run(conn, f"permit_{key}", id=pid, tags=permit[key])
    if permit.get("operates"):
        run(conn, "permit_operates", id=pid, ops=[{"tag": o["tag"], "to": o["to"]} for o in permit["operates"]])


def apply(conn, pid: str, at: str) -> None:
    """Write a permit's state changes into the plant. Call inside a transaction."""
    for stmt in statements(query("apply")):
        conn.execute(stmt, {"id": pid, "at": at})


def activate(conn, pid: str, at: str) -> None:
    """Approve a requested permit: mark it active and record its state changes as planned.

    Approval never writes an observation. The plant's observed states stay as they
    were until someone records what they see with `set_state`.
    """
    run(conn, "permit_activate", id=pid, at=at)
    for stmt in statements(query("plan")):
        conn.execute(stmt, {"id": pid, "at": at})


def close_permit(conn, pid: str, at: str) -> list[dict]:
    """Close a permit. Returns isolation points other active permits still need."""
    got = run(conn, "permit_exists", id=pid)
    if not got or got[0]["status"] != "active":
        raise StoreError(f"no active permit {pid}")
    still = run(conn, "permit_still_needed", id=pid)
    run(conn, "permit_close", id=pid, at=at)
    return still


def component(conn, tag: str) -> dict:
    found = run(conn, "component", tag=tag)
    if not found:
        raise StoreError(f"unknown tag: {tag}")
    return found[0]


def set_state(conn, tag: str, state: str, at: str, by: str) -> None:
    """Record a component's state. Call inside a transaction."""
    comp = component(conn, tag)
    if comp["kind"] not in KINDS:
        raise StoreError(f"{tag}: kind '{comp['kind']}' is not known to this version")
    problem = validate.state_problem(comp["kind"], state, tag)
    if problem:
        raise ValidationError(tag, [problem])
    run(conn, "set_state", tag=tag, state=state, at=at, by=by)


# ---------------------------------------------------------------- evaluations

def record_evaluation(conn, kind: str, request: dict, result: dict, snap: dict, at: str | None = None) -> str:
    """Append an Evaluation. It records; it never changes plant state or permits."""
    with transaction(conn, commit=True):
        got = run(conn, "evaluation_record", at=at or now(), kind=kind,
                  request_id=request.get("id") or "", assessment_status=result.get("assessment_status"),
                  conflict_verdict=result.get("conflict_verdict"),
                  request=json.dumps(request, sort_keys=True),
                  result=json.dumps(result, sort_keys=True),
                  snapshot=json.dumps(snap, sort_keys=True))
    return got[0]["id"]


def get_evaluation(conn, eid: str) -> dict:
    got = run(conn, "evaluation_get", id=eid)
    if not got:
        raise StoreError(f"no evaluation {eid}")
    e = got[0]
    for k in ("request", "result", "snapshot"):
        e[k] = json.loads(e[k])
    return e


def list_evaluations(conn) -> list[dict]:
    return run(conn, "evaluation_list")
