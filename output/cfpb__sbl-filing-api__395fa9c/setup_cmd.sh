#!/bin/bash
set -e
cd /app
uv venv /opt/venv && uv pip install --python /opt/venv/bin/python poetry && /opt/venv/bin/poetry install --with dev
