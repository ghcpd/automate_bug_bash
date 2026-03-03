#!/bin/bash
set -e
cd /app
/app/.venv/bin/python -m pytest --tb=short -q
