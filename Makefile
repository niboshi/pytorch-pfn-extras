SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables
.DEFAULT_GOAL := help

PWD := $(realpath $(dir $(abspath $(firstword $(MAKEFILE_LIST)))))

PY := python
PIP := $(PY) -m pip

.PHONY: format
format: ## Format the Python code.	
	cp "$$($(PIP) show torch | awk '/^Location:/ { print $$2 }')/torch/__init__.py" stubs/torch/__init__.py
	trap "rm -f stubs/torch/__init__.py" EXIT; MYPYPATH="$(PWD)/stubs" $(PY) -m pysen run format lint

.PHONY: lint
lint: ## Lint the Python code.
	cp "$$($(PIP) show torch | awk '/^Location:/ { print $$2 }')/torch/__init__.py" stubs/torch/__init__.py
	trap "rm -f stubs/torch/__init__.py" EXIT; MYPYPATH="$(PWD)/stubs" $(PY) -m pysen run lint

.PHONY: test
test: ## Run all tests.
	$(PY) -m pytest tests

.PHONY: cputest
cputest: ## Run all tests except for ones requiring GPU.
	$(PY) -m pytest -m "not gpu" tests

.PHONY: example_lint
example_lint: ## Format the Python code.
	$(PY) -m pysen --config ./example/pysen.toml run lint

.PHONY: help
help: ## Display this help message.
	@grep -E '^[%%a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
