# We're using Make as a command runner, so always make (avoids need for .PHONY).
MAKEFLAGS += --always-make

help:  # Display help
	@echo "Usage: make [target] [ARGS='additional args']\n\nTargets:"
	@awk -F'#' '/^[a-z0-9-]+:/ { sub(":.*", "", $$1); print " ", $$1, "#", $$2 }' Makefile | column -t -s '#'

all: format lint unit  # Run all quick, local commands

# Please keep the list below in alphabetical order.

coverage-html:  # Write and open HTML coverage report from the last unit test run
	uv run coverage html
	xdg-open htmlcov/index.html 2>/dev/null || open htmlcov/index.html 2>/dev/null

fix:  # Auto-fix linting issues that ruff can fix
	uv run ruff check --preview --fix

format:  # Format the Python code
	uv run ruff format --preview

lint:  # Linting, spell checks, and pyright (strict)
	uv run ruff check --preview
	uv run ruff format --preview --check
	uv run codespell
	uv run pyright $(ARGS)

unit:  # Run unit tests with coverage, eg: make unit ARGS='-k test_pool'
	uv run coverage run --source=src -m pytest $(ARGS) tests
	uv run coverage report
