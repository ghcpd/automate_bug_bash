#!/bin/bash
set -e
cd /app
uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-cov python-decouple icecream --quiet
