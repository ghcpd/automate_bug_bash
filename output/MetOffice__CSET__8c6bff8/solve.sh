#!/usr/bin/env bash
set -euo pipefail

# Install system dependencies for pygraphviz
apt-get update -qq && apt-get install -y -qq graphviz libgraphviz-dev python3-dev pkg-config

cd /app

# Remove mo_pack dependency (conda-only, not on PyPI) and required-version
sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true
sed -i '/mo_pack/d' pyproject.toml
sed -i '/mo-pack/d' pyproject.toml

# Create venv and install
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -e . pytest pytest-cov pytest-xdist --quiet
