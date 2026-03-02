#!/bin/bash
set -e
cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --all-groups --quiet && uv pip install --python .venv/bin/python coverage --quiet
