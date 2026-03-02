FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/Garden-AI/garden.git /app && \
    cd /app && (git checkout fedf8a83d9261b3b6928869c370206c26929ceb7 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin fedf8a83d9261b3b6928869c370206c26929ceb7 && git checkout fedf8a83d9261b3b6928869c370206c26929ceb7 --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --all-groups

# Default command: run tests
CMD ["bash", "-c", "/app/.venv/bin/python -m pytest --tb=short -q"]
