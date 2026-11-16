"""The README says what each command does to the store."""
import re

from conftest import ROOT

README = (ROOT / "README.md").read_text(encoding="utf-8")
RECORDS = ("check", "whatif", "approve", "set", "mcp")      # commands that append an Evaluation


def _row(command):
    rows = [l for l in README.splitlines() if re.match(rf"\| `(?:python -m )?blindflange {command}\b", l)]
    assert rows, f"no README row for {command}"
    return rows[0]


def test_every_command_that_records_an_evaluation_says_so():
    for command in RECORDS:
        row = _row(command)
        assert "Evaluation" in row, row
        assert "changes nothing." not in row.lower(), row


def _quick_start():
    section = README.split("## Setup and run", 1)[1]
    return section.split("```", 2)[1]


def test_quick_start_has_a_venv_and_leads_with_python_m():
    block = _quick_start()
    assert "venv" in block
    runs = [l for l in block.splitlines() if "blindflange " in l and not l.startswith("git clone")]
    assert runs and all(l.lstrip().startswith("python -m blindflange") for l in runs), runs


def test_quick_start_checks_a_gitignored_copy_not_the_committed_store():
    block = _quick_start()
    assert "stores/condensate_unit.rl work.rl" in block
    check = [l for l in block.splitlines() if " check " in l][0]
    assert check.rstrip().endswith("--store work.rl"), check
    assert "work.rl" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_no_readme_command_writes_to_a_committed_store():
    for line in README.splitlines():
        if "--store stores/" in line:
            assert " build " in line or "read_only" in line or line.lstrip().startswith(("cp ", "copy ")), line


def test_every_make_target_has_a_plain_command_beside_it():
    plain = {"install": "pip install", "test": "python -m pytest", "eval": "python eval/compare.py",
             "stores": "python -m blindflange build", "demo": "python -m blindflange check"}
    for line in README.splitlines():
        for target in re.findall(r"`make (\w+)`", line):
            assert plain[target] in line, line


def test_ci_runs_install_tests_and_eval_on_three_systems():
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    assert ci.is_file()
    text = ci.read_text(encoding="utf-8")
    for needle in ("ubuntu-latest", "macos-latest", "windows-latest", '"3.12"',
                   "pip install .", "python -m pytest", "python eval/compare.py"):
        assert needle in text, needle
