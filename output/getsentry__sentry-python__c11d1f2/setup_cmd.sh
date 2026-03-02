#!/bin/bash
set -e
cd /app
uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[pure-eval]" --quiet && uv pip install --python /opt/venv/bin/python -r requirements-testing.txt --quiet && uv pip install --python /opt/venv/bin/python pytest-asyncio --quiet
