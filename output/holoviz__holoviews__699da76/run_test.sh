#!/bin/bash
set -e
cd /app
.venv/bin/python -m pytest --tb=short -q
