PYTHON ?= python3
VENV := .venv
UV ?= uv
SOVEREIGN := $(VENV)/bin/sovereign
PY := $(VENV)/bin/python

.PHONY: help install sync test test-all coverage lint format typecheck check quality audit hooks minimum browser-check bench \
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
	@echo "make check           lint + format check + typecheck + test with coverage"
	@echo "make quality         check + dependency audit"
	@echo "make audit           pip-audit against the locked third-party dependencies"
	@echo "make hooks           install the pre-commit hooks"
	@echo "make minimum         test against the oldest allowed dependencies"
	@echo "make browser-check   live Chromium end-to-end tests (Playwright)"
	@echo "make build           build the wheel and sdist"
	@echo "make clean           remove build artefacts and caches"

install:
	$(UV) sync --all-extras --dev --python $(PYTHON)
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
	# CI runs on Linux, where sys.platform narrows; check that view too.
	$(VENV)/bin/mypy --platform linux

check: lint typecheck coverage
	$(VENV)/bin/ruff format --check .

audit:
	$(UV) export --no-emit-project --no-hashes -o /tmp/sovereign-audit-requirements.txt
	$(VENV)/bin/pip-audit --strict -r /tmp/sovereign-audit-requirements.txt

hooks:
	$(VENV)/bin/pre-commit install

minimum:
	$(UV) pip compile pyproject.toml --extra dev --extra browser --resolution lowest-direct -o /tmp/sovereign-minimum.txt
	rm -rf /tmp/sovereign-minimum-venv
	$(UV) venv --python $(PYTHON) /tmp/sovereign-minimum-venv
	$(UV) pip install --python /tmp/sovereign-minimum-venv/bin/python -r /tmp/sovereign-minimum.txt
	$(UV) pip install --python /tmp/sovereign-minimum-venv/bin/python -e . --no-deps
	/tmp/sovereign-minimum-venv/bin/python -m pytest -q

browser-check:
	$(PY) -m pytest -q -m integration tests/test_browser_live.py

quality: check audit

bench:
	$(SOVEREIGN) bench

run:
	$(SOVEREIGN)

start:
	bash bin/sovereign-start.command

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
