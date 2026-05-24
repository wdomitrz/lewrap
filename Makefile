.PHONY: all lint fix test

all: fix lint test

lint:
	uv run ruff check .
	uv run basedpyright --project pyproject.toml --level error .

fix:
	uv run ruff check --extend-select I --fix-only --fix .
	uv run ruff format .

test:
	uv run python -m doctest README.md $(wildcard *.py)
