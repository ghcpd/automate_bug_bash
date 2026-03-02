#!/bin/bash
set -e
cd /app
/opt/venv/bin/python -m pytest tests/ --tb=short -q --override-ini='addopts=' --ignore=tests/integrations
