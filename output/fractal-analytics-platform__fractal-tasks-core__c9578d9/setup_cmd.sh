#!/bin/bash
set -e
cd /app
uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest devtools coverage jsonschema requests pooch --quiet && uv pip install --python /opt/venv/bin/python /app/tests/data/napari_workflows/mock_package/dist/napari_skimage_regionprops_mock-9.9.9-py3-none-any.whl --quiet
