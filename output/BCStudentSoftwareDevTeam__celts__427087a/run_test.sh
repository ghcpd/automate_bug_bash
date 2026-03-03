#!/bin/bash
set -e
cd /app
cd /app && APP_ENV=testing /opt/venv/bin/python -m pytest --tb=short -q --ignore=tests/mail_test.py --ignore=tests/ui --ignore=database -m "unit or integration"
