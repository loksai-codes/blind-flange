"""The README says what each command does to the store."""
import re

from conftest import ROOT

README = (ROOT / "README.md").read_text(encoding="utf-8")
RECORDS = ("check", "whatif", "approve", "set", "mcp")      # commands that append an Evaluation


def _row(command):
    rows = [l for l in README.splitlines() if re.match(rf"\| `blindflange {command}\b", l)]
    assert rows, f"no README row for {command}"
    return rows[0]


def test_every_command_that_records_an_evaluation_says_so():
    for command in RECORDS:
        row = _row(command)
        assert "Evaluation" in row, row
        assert "changes nothing." not in row.lower(), row
