#!/bin/bash
set -e
cd /app
uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -r requirements-base.txt -r requirements-dev.txt pytest --quiet
