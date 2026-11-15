.PHONY: install stores test eval demo

install:
	python -m pip install -e ".[dev]"

stores:
	python -m blindflange build data/scenarios/condensate_unit.yaml -o stores/condensate_unit.rl

test:
	python -m pytest -q

eval:
	python eval/compare.py

demo: stores
	python -m blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
