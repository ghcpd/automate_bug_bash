#!/usr/bin/env bash
set -euo pipefail

cd /app/argilla
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -e '.[dev]' --quiet
uv pip install --python /opt/venv/bin/python pytest pytest-mock pytest-httpx pyarrow markdown --quiet
