PYTHON ?= python3
VENV := .venv
UV ?= uv
SOVEREIGN := $(VENV)/bin/sovereign
PY := $(VENV)/bin/python

.PHONY: help install sync test test-all coverage lint format typecheck check quality bench \
        run status models doctor clients install-clients code login \
        uninstall-login build clean

help:
	@echo "make install         create the venv and install the package"
	@echo "make sync            refresh the lockfile and reinstall"
	@echo "make test            run the test suite"
	@echo "make test-all        run the test suite including integration tests"
	@echo "make coverage        run the test suite and report coverage"
	@echo "make lint            ruff check"
	@echo "make format          ruff format"
	@echo "make typecheck       mypy"
	@echo "make check           lint + format check + typecheck + test"
	@echo "make build           build the wheel and sdist"
	@echo "make clean           remove build artefacts and caches"

install:
	$(UV) venv --python $(PYTHON) $(VENV)
	$(UV) pip install --python $(PY) -e '.[dev,browser]'
	$(SOVEREIGN) install-clients

sync:
	$(UV) lock
	$(UV) sync --all-extras --dev

test:
	$(PY) -m pytest -q

test-all:
	$(PY) -m pytest -q -m "integration or not integration"

coverage:
	$(PY) -m pytest -q --cov=sovereign_code --cov-report=term-missing

lint:
	$(VENV)/bin/ruff check .

format:
	$(VENV)/bin/ruff format .

typecheck:
	$(VENV)/bin/mypy

check: lint typecheck test
	$(VENV)/bin/ruff format --check .

quality: check
	$(VENV)/bin/pip-audit --strict || $(VENV)/bin/pip-audit

bench:
	$(SOVEREIGN) bench

run:
	$(SOVEREIGN)

status:
	$(SOVEREIGN) status

models:
	$(SOVEREIGN) models

doctor:
	$(SOVEREIGN) doctor

clients:
	$(SOVEREIGN) clients

install-clients:
	$(SOVEREIGN) install-clients

code:
	$(SOVEREIGN) code $(path)

login:
	$(SOVEREIGN) install-login

uninstall-login:
	$(SOVEREIGN) uninstall-login

build:
	$(UV) build

clean:
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache htmlcov coverage.xml .coverage
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
