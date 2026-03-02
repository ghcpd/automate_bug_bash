#!/bin/bash
set -e
cd /app
/app/.venv/bin/python -m pytest --tb=short -q --ignore=tests/external --ignore=tests/packages --ignore=tests/contrib/encoding/test_msgspec.py
