#!/bin/bash
set -e
cd /app
cd /app && .venv/bin/python -m pytest backend/tests/unit --tb=short -q
