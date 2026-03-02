#!/bin/bash
set -e
cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-cov pytest-asyncio httpx protobuf lz4 pillow pandas --quiet && uv pip install --python /opt/venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu --quiet
