#!/bin/bash
set -euo pipefail
cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null || true
uv sync --dev
