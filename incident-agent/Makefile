.PHONY: dev migrate test

dev:
	docker-compose up --build

dev-with-simulator:
	docker-compose --profile simulator up --build

migrate:
	python -m shared.db
	python -m runbooks.seed

test:
	pytest -q

simulate-once:
	python -m simulator.datadog_simulator --mode once

simulate-loop:
	python -m simulator.datadog_simulator --mode loop
