#!/bin/bash
set -e
cd /app
cd /app && sed -i 's/"boto3 == 1.7.64"/"boto3"/' setup.py && sed -i 's/"unidecode == 1.0.22"/"unidecode"/' setup.py && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python 'xarray>=2023.0' 'numpy>=1.24' 'pandas>=2.0' --quiet && uv pip install --python /opt/venv/bin/python -e '.[dev]' --quiet && uv pip install --python /opt/venv/bin/python 'boto3>=1.26' 'moto[s3]>=4.0,<5' 'setuptools<81' pytest --quiet
