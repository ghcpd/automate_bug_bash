#!/bin/bash
set -e
cd /app
/opt/venv/bin/python -m pytest --tb=no -q
