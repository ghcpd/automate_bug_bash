FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/docarray/docarray.git /app && \
    cd /app && (git checkout f5fc0f6d5f3dcb0201dc735262ef3256bdf054b9 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin f5fc0f6d5f3dcb0201dc735262ef3256bdf054b9 && git checkout f5fc0f6d5f3dcb0201dc735262ef3256bdf054b9 --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-cov pytest-asyncio httpx protobuf lz4 pillow pandas --quiet && uv pip install --python /opt/venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=no -q --continue-on-collection-errors"]
