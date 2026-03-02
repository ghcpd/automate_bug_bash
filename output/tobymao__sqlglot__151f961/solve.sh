#!/usr/bin/env bash
set -euo pipefail
cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null || true
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -e ".[dev]" --quiet
uv pip install --python /opt/venv/bin/python pytest --quiet
