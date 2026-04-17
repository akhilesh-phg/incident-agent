.PHONY: dev migrate test

dev:
	docker-compose up --build

migrate:
	python -m shared.db
	python -m runbooks.seed

test:
	pytest -q
