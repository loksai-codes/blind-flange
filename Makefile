.PHONY: install stores test eval demo

install:
	pip install -e ".[dev]"

stores:
	blindflange build data/scenarios/condensate_unit.yaml -o stores/condensate_unit.rl

test:
	pytest -q

eval:
	python eval/compare.py

demo: stores
	blindflange check data/permits/PTW-0511.yaml --store stores/condensate_unit.rl
