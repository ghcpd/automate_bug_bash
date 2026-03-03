#!/usr/bin/env bash
set -e
cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null || true
uv sync --group dev
