FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/tobymao/sqlglot.git /app && \
    cd /app && (git checkout 151f961f6575e9cdd54a1cab3dad66fa2a12774c --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 151f961f6575e9cdd54a1cab3dad66fa2a12774c && git checkout 151f961f6575e9cdd54a1cab3dad66fa2a12774c --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[dev]" --quiet && uv pip install --python /opt/venv/bin/python pytest --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
