#!/usr/bin/env bash
set -euo pipefail

cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null || true
uv python install 3.10
uv sync --dev --python 3.10
