#!/bin/bash
set -e
cd /app
uv venv /opt/venv --quiet && { uv pip install --python /opt/venv/bin/python -r requirements-dev.txt --quiet 2>/dev/null; true; } && uv pip install --python /opt/venv/bin/python -r requirements.txt --quiet && uv pip install --python /opt/venv/bin/python pytest --quiet
