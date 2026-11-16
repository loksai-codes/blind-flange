"""The vocabulary of the graph model. See schema/schema.cypher for the data dictionary."""

# component kind -> node label
KINDS = {
    "pump": "Equipment", "vessel": "Equipment", "header": "Equipment",
    "exchanger": "Equipment", "strainer": "Equipment",
    "line": "Line",
    "valve": "Valve", "check_valve": "Valve", "psv": "Valve",
    "blind": "Blind",
}

# valid states per label
STATES = {
    "Valve": {"open", "closed", "removed"},
    "Blind": {"installed", "removed"},
    "Line": {"in_service", "removed"},
    "Equipment": {"in_service", "shutdown", "removed"},
}

INTEGRITY = {"rated", "temporary"}

# permit YAML key -> relationship type
RELATIONS = {"works_on": "WORKS_ON", "relies_on": "RELIES_ON", "energises": "ENERGISES"}

PERMIT_STATUS = {"requested", "active", "closed"}


def label_for(kind: str) -> str:
    return KINDS[kind]
