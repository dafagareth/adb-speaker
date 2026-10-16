# Project: adb-speaker
# File: Makefile
# Description: Development workflow targets for test, lint, format, build, and packaging.
#
# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT
# Licensed under the MIT License (see LICENSE in repository root).
# https://opensource.org/licenses/MIT

.DEFAULT_GOAL := help
PYTHON ?= python3

.PHONY: help test lint format test-native build-receiver bundle-receiver check-receiver portable smoke clean
help:
	@printf '%s\n' \
		'make test             Run host tests without a phone' \
		'make lint             Check Python formatting and lint' \
		'make format           Format Python files' \
		'make test-native      Test C++ audio conversion and resampling' \
		'make build-receiver   Compile Android receiver' \
		'make bundle-receiver  Update bundled receiver and source marker' \
		'make check-receiver   Verify receiver source marker' \
		'make portable         Build Linux portable archive in Docker' \
		'make smoke            Check the Linux archive in a clean container' \
		'make clean            Remove build artifacts, caches, and bytecode'

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
format:
	$(PYTHON) -m ruff format .
test-native:
	cmake -S native/windows -B build/native -DCMAKE_BUILD_TYPE=Release
	cmake --build build/native --config Release
	ctest --test-dir build/native -C Release --output-on-failure
build-receiver:
	$(PYTHON) scripts/receiver.py build
bundle-receiver:
	$(PYTHON) scripts/receiver.py bundle
check-receiver:
	$(PYTHON) scripts/receiver.py check
portable:
	docker build --target artifact --output type=local,dest=dist -f packaging/linux/Dockerfile .
smoke:
	cd dist && sha256sum -c SHA256SUMS
	sh packaging/linux/smoke.sh
clean:
	rm -rf build dist src/*.egg-info .ruff_cache .cache compile_commands.json
	find . -type d -name '__pycache__' -not -path './.venv*' -exec rm -rf {} +
	find . -type f -name '*.pyc' -not -path './.venv*' -delete
