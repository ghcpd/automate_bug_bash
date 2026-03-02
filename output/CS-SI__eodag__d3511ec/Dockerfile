FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/CS-SI/eodag.git /app && \
    cd /app && (git checkout d3511ecdb2501939fac65e81451551e025cb6b05 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin d3511ecdb2501939fac65e81451551e025cb6b05 && git checkout d3511ecdb2501939fac65e81451551e025cb6b05 --quiet))
WORKDIR /app

# Install dependencies
RUN cd /app && sed -i 's/"boto3 == 1.7.64"/"boto3"/' setup.py && sed -i 's/"unidecode == 1.0.22"/"unidecode"/' setup.py && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python 'xarray>=2023.0' 'numpy>=1.24' 'pandas>=2.0' --quiet && uv pip install --python /opt/venv/bin/python -e '.[dev]' --quiet && uv pip install --python /opt/venv/bin/python 'boto3>=1.26' 'moto[s3]>=4.0,<5' 'setuptools<81' pytest --quiet

# Default command: run tests
CMD ["bash", "-c", "cd /app && /opt/venv/bin/python -m pytest --tb=short -q"]
