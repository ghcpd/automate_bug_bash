#!/bin/bash
set -e
cd /app
uv python install 3.11 && uv venv /opt/venv --python 3.11 --quiet --clear && uv pip install --python /opt/venv/bin/python -r requirements.txt --quiet && uv pip install --python /opt/venv/bin/python 'setuptools<71' --quiet
