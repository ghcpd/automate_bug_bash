#!/usr/bin/env bash
set -euo pipefail

cd /app

# Initialize the python_sdk submodule (it's a git submodule)
git submodule update --init --recursive python_sdk

# Remove required-version constraint that may conflict with installed uv
sed -i '/^required-version/d' pyproject.toml 2>/dev/null || true

# Install all dependencies using uv sync
uv sync --all-groups
