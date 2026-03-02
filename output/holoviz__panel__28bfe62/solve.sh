#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null || true
uv venv /opt/venv --quiet
PANEL_LITE=1 uv pip install --python /opt/venv/bin/python -e ".[tests]" --quiet
