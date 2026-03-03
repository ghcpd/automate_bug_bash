#!/bin/bash
set -e
cd /app
cd /app/argilla && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e '.[dev]' --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-mock pytest-httpx pyarrow markdown --quiet
