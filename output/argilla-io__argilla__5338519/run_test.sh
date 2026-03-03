#!/bin/bash
set -e
cd /app
cd /app/argilla && /opt/venv/bin/python -m pytest tests/unit --tb=short -q
