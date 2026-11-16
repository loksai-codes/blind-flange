.PHONY: install plants stores test eval demo

PY ?= python

install:
	$(PY) -m pip install -e ".[dev]"

plants:
	$(PY) data/plants/make_gas_plant.py

stores:
	$(PY) -m blindflange build data/scenarios/condensate_unit.yaml -o stores/condensate_unit.rl
	$(PY) -m blindflange build data/scenarios/gas_plant.yaml -o stores/gas_plant.rl

test:
	$(PY) -m pytest -q

eval:
	$(PY) eval/compare.py

demo:
	$(PY) -m blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl || true
	$(PY) -m blindflange check data/permits/PTW-2201.yaml --store stores/gas_plant.rl || true
