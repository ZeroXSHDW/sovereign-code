PYTHON ?= python3
VENV := .venv
SOVEREIGN := $(VENV)/bin/sovereign

.PHONY: install test run status models doctor clients install-clients login uninstall-login

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -e '.[dev]'
	$(SOVEREIGN) install-clients

test:
	$(VENV)/bin/python -m pytest -q

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
