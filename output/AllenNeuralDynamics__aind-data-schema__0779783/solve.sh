#!/usr/bin/env bash
set -euo pipefail
cd /app
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -e ".[dev]" pytest --quiet
