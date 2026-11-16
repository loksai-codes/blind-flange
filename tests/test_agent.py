"""The agent tools, called directly and over MCP stdio."""
import json
import subprocess
import sys

import pytest

from blindflange import agent, store
from conftest import SCENARIO


@pytest.fixture
def rl(tmp_path):
    out = tmp_path / "s.rl"
    store.build(SCENARIO, out).close()
    return str(out)


def test_assess_change_gives_the_same_verdict_as_the_cli_path(rl):
    d = agent.call(rl, "assess_change", {"changes": [{"tag": "P-A", "to": "in_service"}]})
    assert (d["assessment_status"], d["conflict_verdict"]) == ("COMPLETE", "BLOCK")
    assert d["findings"][0]["path"] == ["P-A", "L-PD-A", "RLV-504", "L-RL-504", "BF-504"]


def test_what_if_changes_nothing(rl):
    d = agent.call(rl, "what_if", {"changes": [{"tag": "RLV-504", "to": "closed"}],
                                   "permit": {"id": "PTW-A", "energises": ["P-A"],
                                              "operates": [{"tag": "SV-A", "to": "open"}]}})
    assert d["conflict_verdict"] == "CLEAR"
    conn = store.connect(rl, read_only=True)
    try:
        assert store.component(conn, "RLV-504")["state"] == "open"
        assert not store.run(conn, "permit_exists", id="PTW-A")
    finally:
        conn.close()


def test_agent_tools_cannot_change_plant_state():
    names = {t["name"] for t in agent.TOOLS}
    assert names == {"assess_change", "what_if", "reach", "handover", "find_tags", "get_evaluation",
                     "trace_path", "explain_finding", "list_requests"}


def test_get_evaluation_reports_replay(rl):
    d = agent.call(rl, "assess_change", {"permit": {"id": "PTW-X", "energises": ["P-A"]}})
    e = agent.call(rl, "get_evaluation", {"id": d["evaluation_id"]})
    assert e["replay_reproduces"] and e["kind"] == "agent:assess_change"


def test_bad_arguments_are_tool_errors_not_crashes(rl):
    with pytest.raises(agent.ToolError):
        agent.call(rl, "assess_change", {})
    r = agent.handle(rl, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "assess_change", "arguments": {"changes": [{"tag": "NOPE", "to": "open"}]}}})
    assert r["result"]["isError"] is False                       # an ERROR result, recorded
    assert r["result"]["structuredContent"]["assessment_status"] == "ERROR"


def test_mcp_stdio_session(rl):
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "find_tags", "arguments": {"text": "pump A relief valve"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "assess_change", "arguments": {"changes": [{"tag": "P-A", "to": "in_service"}]}}},
    ]
    p = subprocess.run([sys.executable, "-m", "blindflange", "mcp", "--store", rl],
                       input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, timeout=60)
    out = [json.loads(line) for line in p.stdout.splitlines()]
    assert [o["id"] for o in out] == [1, 2, 3, 4]
    assert out[0]["result"]["protocolVersion"] == "2025-06-18"
    assert len(out[1]["result"]["tools"]) == 9
    assert any(m["tag"] == "PSV-504" for m in out[2]["result"]["structuredContent"]["matches"])
    assert out[3]["result"]["structuredContent"]["conflict_verdict"] == "BLOCK"


def test_handover_tool_does_not_change_the_store_file(rl):
    from pathlib import Path
    before = Path(rl).read_bytes()
    agent.call(rl, "handover", {})
    assert Path(rl).read_bytes() == before


def test_trace_path_shows_the_proven_route_and_the_barriers_on_the_physical_one(rl):
    d = agent.call(rl, "trace_path", {"from": "P-A", "to": "BF-504"})
    assert [n["tag"] for n in d["proven"]["nodes"]] == ["P-A", "L-PD-A", "RLV-504", "L-RL-504", "BF-504"]
    d = agent.call(rl, "trace_path", {"from": "JT-DRUM", "to": "BF-504"})
    assert d["proven"] is None and d["possible"] is None              # SV-A is closed
    assert {"tag": "SV-A", "state": "closed"} in [{k: b[k] for k in ("tag", "state")}
                                                 for b in d["physical"]["barriers"]]


def test_trace_path_rejects_unknown_tags(rl):
    with pytest.raises(store.StoreError):
        agent.call(rl, "trace_path", {"from": "P-A", "to": "NOPE"})


def test_explain_finding_walks_the_recorded_path_with_barriers_beside_it(tmp_path):
    from conftest import ROOT
    gas = tmp_path / "gas.rl"
    store.build(ROOT / "data" / "scenarios" / "gas_plant.yaml", gas).close()
    perm = store.load_permit(ROOT / "data" / "permits" / "PTW-2201.yaml")
    d = agent.call(str(gas), "assess_change", {"permit": perm})
    e = agent.call(str(gas), "explain_finding", {"evaluation_id": d["evaluation_id"], "finding": 1})
    assert (e["code"], e["verdict"], e["certainty"]) == ("PRESSURE_REACHES_TEMPORARY_BARRIER", "BLOCK", "PROVEN")
    steps = {s["tag"]: s for s in e["steps"]}
    assert len(e["steps"]) == 13 and steps["SDV-110"]["state"] == "open" and steps["SDV-110"]["changed_by_request"]
    assert {"tag": "XV-231", "state": "closed"} in steps["L-231"]["barriers_beside"]


def test_exploration_tools_do_not_change_the_store(rl):
    from pathlib import Path
    before = Path(rl).read_bytes()
    agent.call(rl, "trace_path", {"from": "P-A", "to": "BF-504"})
    assert Path(rl).read_bytes() == before


def test_agent_call_waits_briefly_for_a_store_another_process_holds(rl):
    import threading
    import time
    opened = threading.Event()

    def hold():                                      # another writer holds the file for a moment
        conn = store.connect(rl)                     # Relate connections are thread-affine
        opened.set()
        time.sleep(0.6)
        conn.close()

    t = threading.Thread(target=hold)
    t.start()
    opened.wait(10)
    try:
        d = agent.call(rl, "find_tags", {"text": "pump A"})
    finally:
        t.join()
    assert d["matches"]


def test_agent_call_gives_up_with_a_clear_error_if_the_store_stays_locked(rl, monkeypatch):
    monkeypatch.setattr(agent, "LOCK_WAIT_SECONDS", 0.3)
    holder = store.connect(rl)
    try:
        with pytest.raises(store.StoreError, match="another process"):
            agent.call(rl, "find_tags", {"text": "pump A"})
    finally:
        holder.close()



def _permits():
    from conftest import ROOT
    return str(ROOT / "data" / "permits")


def test_list_requests_shows_only_this_plants_written_requests(rl):
    d = agent.call(rl, "list_requests", {}, permits_dir=_permits())
    ids = {r["id"] for r in d["requests"]}
    assert "PTW-0511" in ids and not any(i.startswith("PTW-22") for i in ids)
    assert d["other_plants"] >= 7
    r = next(r for r in d["requests"] if r["id"] == "PTW-0511")
    assert r["energises"] == ["P-A"] and r["operates"] == [{"tag": "SV-A", "to": "open"}]


def test_a_written_request_by_id_is_assessed_exactly_as_written(tmp_path):
    """The partial-scope trap: starting K-220 alone is CLEAR, the written restart permit is BLOCK."""
    from conftest import ROOT
    gas = tmp_path / "gas.rl"
    store.build(ROOT / "data" / "scenarios" / "gas_plant.yaml", gas).close()
    part = agent.call(str(gas), "assess_change", {"changes": [{"tag": "K-220", "to": "in_service"}]})
    assert part["conflict_verdict"] == "CLEAR"
    whole = agent.call(str(gas), "assess_change", {"permit_id": "PTW-2201"}, permits_dir=_permits())
    by_hand = agent.call(str(gas), "assess_change",
                         {"permit": store.load_permit(ROOT / "data" / "permits" / "PTW-2201.yaml")})
    assert whole["conflict_verdict"] == by_hand["conflict_verdict"] == "BLOCK"
    assert whole["findings"] == by_hand["findings"]
    assert whole["tag_matching_baseline"].startswith("PASS") and "not the plant's state before" in \
        whole["tag_matching_baseline"]
    w = agent.call(str(gas), "what_if", {"changes": [{"tag": "BV-231", "to": "closed"}], "permit_id": "PTW-2201"},
                   permits_dir=_permits())
    assert w["conflict_verdict"] == "CLEAR"


def test_permit_id_errors_are_tool_errors(rl):
    with pytest.raises(agent.ToolError, match="--permits"):
        agent.call(rl, "assess_change", {"permit_id": "PTW-0511"})
    with pytest.raises(agent.ToolError, match="no written request"):
        agent.call(rl, "assess_change", {"permit_id": "PTW-9999"}, permits_dir=_permits())
    with pytest.raises(agent.ToolError, match="not both"):
        agent.call(rl, "assess_change", {"permit_id": "PTW-0511", "permit": {"id": "X"}}, permits_dir=_permits())
    with pytest.raises(agent.ToolError, match="--permits"):
        agent.call(rl, "list_requests", {})


def test_mcp_stdio_session_with_permits_folder(rl):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_requests", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "assess_change", "arguments": {"permit_id": "PTW-0511"}}}]
    p = subprocess.run([sys.executable, "-m", "blindflange", "mcp", "--store", rl, "--permits", _permits()],
                       input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, timeout=60)
    out = [json.loads(line) for line in p.stdout.splitlines()]
    assert any(r["id"] == "PTW-0511" for r in out[0]["result"]["structuredContent"]["requests"])
    assert out[1]["result"]["structuredContent"]["conflict_verdict"] == "BLOCK"
