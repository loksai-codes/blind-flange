"""The vocabulary of the graph model. See schema/schema.cypher for the data dictionary."""

# component kind -> node label
KINDS = {
    "pump": "Equipment", "compressor": "Equipment", "vessel": "Equipment", "header": "Equipment",
    "exchanger": "Equipment", "strainer": "Equipment", "filter": "Equipment",
    "line": "Line",
    "valve": "Valve", "check_valve": "Valve", "control_valve": "Valve", "psv": "Valve",
    "blind": "Blind",
}

LABELS = ("Equipment", "Line", "Valve", "Blind")

UNKNOWN = "unknown"

# Valid states per label. A blind is never "removed": that word is ambiguous for a
# blind (blind taken out, or spool taken out?), so blinds are installed or not_installed.
STATES = {
    "Valve": {"open", "closed", "removed", UNKNOWN},
    "Blind": {"installed", "not_installed", UNKNOWN},
    "Line": {"in_service", "removed", UNKNOWN},
    "Equipment": {"in_service", "shutdown", "removed", UNKNOWN},
}

# Passability, the one rule (also in queries/exposures.cypher, queries/reach.cypher,
# queries/bound.cypher and docs/SPEC.md):
#   closed, installed  barrier: pressure reaches it and stops
#   removed            open end: pressure reaches it, escapes, and does not continue
#   unknown            not known: never a barrier; the walk may pass it, but only as POSSIBLE
#   anything else      passes
BARRIER = ("closed", "installed")
OPEN_END = "removed"

INTEGRITY = {"rated", "temporary"}

# permit YAML key -> relationship type
RELATIONS = {"works_on": "WORKS_ON", "relies_on": "RELIES_ON", "energises": "ENERGISES"}

PERMIT_STATUS = {"requested", "active", "closed"}

# The rules an assessment follows. Every Evaluation records RULES_VERSION, so a
# replay can say when a result was made under different rules. RULES_SHA is a
# fingerprint of the rule-defining queries; tests/test_rules_version.py fails if
# they change without a new version (and a line in the history in docs/SPEC.md).
RULES_VERSION = 4
RULES_FILES = ("exposures", "bound", "direct", "apply", "plan", "reach", "trace")
RULES_SHA = "bc8cac2d195a8cab"

# Defaults for an assessment.
DEFAULT_MAX_HOPS = 100          # Relate refuses explicit path bounds above 500
MAX_HOPS_LIMIT = 499            # the bound probe uses max_hops + 1
DEFAULT_MAX_AGE_HOURS = 12      # one shift


def label_for(kind: str) -> str:
    return KINDS[kind]


def valid_states(kind: str) -> set[str]:
    return STATES[KINDS[kind]]
