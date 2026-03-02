#!/usr/bin/env bash
set -euo pipefail

cd /app

# Create virtual environment
uv venv /opt/venv --quiet

# Install the package in editable mode with pure-eval extras
uv pip install --python /opt/venv/bin/python -e ".[pure-eval]" --quiet

# Install testing dependencies
uv pip install --python /opt/venv/bin/python -r requirements-testing.txt --quiet

# Install pytest-asyncio for async test support
uv pip install --python /opt/venv/bin/python pytest-asyncio --quiet
