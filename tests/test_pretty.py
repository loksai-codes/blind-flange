"""Styled terminal output: drawn only when asked for or on a terminal, and saying the same things."""
import io
import re
import subprocess
import sys

import pytest

from blindflange import pretty, store
from conftest import ROOT

ANSI = re.compile(r"\x1b\[[0-9;]*m")
GAS_PATH = ["V-110", "L-110G", "SDV-110", "L-SUCT", "BV-231", "L-231", "V-230", "L-230S", "K-230", "L-230D",
            "RV-230", "L-230R", "BF-230"]


@pytest.fixture
def gas(tmp_path):
    out = tmp_path / "gas.rl"
    store.build(ROOT / "data" / "scenarios" / "gas_plant.yaml", out).close()
    return str(out)


def _run(*args, env=None):
    import os
    return subprocess.run([sys.executable, "-m", "blindflange", *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env={**os.environ, **(env or {})})


def test_styled_output_draws_the_whole_path_with_its_barriers(gas):
    p = _run("check", str(ROOT / "data" / "permits" / "PTW-2201.yaml"), "--store", gas, "--color", "always")
    assert p.returncode == 2 and "\x1b[" in p.stdout
    text = ANSI.sub("", p.stdout)
    assert "BLOCK" in text and "PRESSURE_REACHES_TEMPORARY_BARRIER" in text and "12 hops" in text
    rail = [line.split()[1] for line in text.splitlines() if line.strip()[:1] in "┌│└" and
            len(line.split()) > 1 and line.split()[1] in GAS_PATH]
    assert rail == GAS_PATH                                           # every step, in order
    assert "closed → open" in text and "◆ this request" in text       # SDV-110, changed by the permit
    assert "XV-231 closed" in text                                    # the isolation the bypass gets around
    assert "untested blind · PTW-1230 relies on it" in text
    assert "so it would miss this" in text                            # tag matching passes it


def test_a_pipe_gets_the_plain_text_unless_colour_is_forced(gas):
    permit = str(ROOT / "data" / "permits" / "PTW-2201.yaml")
    plain = _run("check", permit, "--store", gas)
    assert "\x1b[" not in plain.stdout and "Path (12 hops): V-110 -> L-110G" in plain.stdout
    assert "\x1b[" not in _run("check", permit, "--store", gas, "--color", "never").stdout
    assert "\x1b[" in _run("check", permit, "--store", gas, env={"FORCE_COLOR": "1"}).stdout
    assert "\x1b[" not in _run("check", permit, "--store", gas, "--json", "--color", "always").stdout


def test_what_if_changes_are_labelled_as_assumed_not_as_the_request(tmp_path):
    rl = tmp_path / "c.rl"
    store.build(ROOT / "data" / "scenarios" / "condensate_unit.yaml", rl).close()
    p = _run("whatif", "--set", "RLV-504=unknown", "--permit", str(ROOT / "data" / "permits" / "PTW-0511.yaml"),
             "--store", str(rl), "--color", "always")
    text = ANSI.sub("", p.stdout)
    assert p.returncode == 3 and "NO VERDICT" in text and "INCOMPLETE" in text
    assert "◆ what-if" in text and "? unconfirmed" in text
    assert "started by this request" in text                           # P-A is energised by the permit


def test_wanted_respects_no_color_and_non_terminals(monkeypatch):
    class Tty(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(pretty, "_windows_vt", lambda: True)
    assert pretty.wanted("auto", Tty())
    assert not pretty.wanted("never", Tty())
    assert not pretty.wanted("auto", io.StringIO())                    # not a terminal
    monkeypatch.setenv("NO_COLOR", "1")
    assert not pretty.wanted("auto", Tty())
    assert pretty.wanted("always", Tty())
