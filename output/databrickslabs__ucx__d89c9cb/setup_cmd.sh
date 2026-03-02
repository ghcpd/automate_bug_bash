#!/bin/bash
set -e
cd /app
sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python 'pytest~=8.3.3' 'pytest-cov~=4.1.0' 'pytest-mock~=3.14.0' 'pytest-timeout~=2.3.1' 'pytest-xdist~=3.5.0' 'databricks-labs-pytester>=0.7.2' 'python-lsp-server>=1.9.0' --quiet && rm -rf /app/.venv && ln -s /opt/venv /app/.venv
