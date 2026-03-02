FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/opsmill/infrahub.git /app && \
    cd /app && (git checkout 9301129ee10f1403da5dd46738a891a7fcc04ed9 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 9301129ee10f1403da5dd46738a891a7fcc04ed9 && git checkout 9301129ee10f1403da5dd46738a891a7fcc04ed9 --quiet))
WORKDIR /app

# Install dependencies
RUN cd /app && git submodule update --init --recursive python_sdk && sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --all-groups

# Default command: run tests
CMD ["bash", "-c", "cd /app && .venv/bin/python -m pytest backend/tests/unit --tb=short -q"]
