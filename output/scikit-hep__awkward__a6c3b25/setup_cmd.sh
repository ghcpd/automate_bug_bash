#!/bin/bash
set -e
cd /app
uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python awkward-cpp==52 --quiet && uv pip install --python /opt/venv/bin/python -e /app --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-xdist --quiet
