.PHONY: all lint fix test

all: fix lint test

lint:
	ruff check .
	basedpyright --project pyproject.toml --level error .

fix:
	ruff check --extend-select I --fix-only --fix .
	ruff format .

test:
	python3 -m doctest README.md $(wildcard *.py)
