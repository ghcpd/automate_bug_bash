#!/bin/bash
set -e
cd /app
/opt/venv/bin/python -m pytest --ignore=tests/tasks --tb=short -q
