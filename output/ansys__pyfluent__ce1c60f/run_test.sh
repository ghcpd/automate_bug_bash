#!/bin/bash
set -e
cd /app
/opt/venv/bin/python -m pytest --tb=short -q --ignore=tests/test_field_data.py --ignore=tests/test_settings_api.py
