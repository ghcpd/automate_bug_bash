FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/sdv-dev/SDMetrics.git /app && \
    cd /app && (git checkout 7b5c44d4576ca4ff939fb221e32c8ae43d2946db --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 7b5c44d4576ca4ff939fb221e32c8ae43d2946db && git checkout 7b5c44d4576ca4ff939fb221e32c8ae43d2946db --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[dev,test]" --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
