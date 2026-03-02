#!/bin/bash
set -e
cd /app
cd /app && git submodule update --init --recursive python_sdk && sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --all-groups
