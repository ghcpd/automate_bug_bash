FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/reflex-dev/reflex.git /app && \
    cd /app && (git checkout e7c374215e568ec32b5cdc1d64c11030cb453bfd --quiet 2>/dev/null || \
    (git fetch --depth=1 origin e7c374215e568ec32b5cdc1d64c11030cb453bfd && git checkout e7c374215e568ec32b5cdc1d64c11030cb453bfd --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --dev --quiet

# Default command: run tests
CMD ["bash", "-c", "/app/.venv/bin/python -m pytest --tb=short -q"]
