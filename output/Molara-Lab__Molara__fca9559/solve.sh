#!/usr/bin/env bash
set -euo pipefail

# Install system dependencies for Cython compilation and Qt runtime
apt-get update -qq
apt-get install -y -qq python3-dev build-essential libgl1-mesa-dev libxkbcommon-x11-0 \
  libglib2.0-0 libegl1 libxcb-xinerama0 libxcb-cursor0 xvfb \
  libfontconfig1 libdbus-1-3 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-shape0

# Create venv and install package with test dependencies
cd /app
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -e ".[tests]" --quiet
