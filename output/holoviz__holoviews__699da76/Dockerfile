FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/holoviz/holoviews.git /app && \
    cd /app && (git checkout 699da76b1d5b907fbe45dd4228e76df46138c6fc --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 699da76b1d5b907fbe45dd4228e76df46138c6fc && git checkout 699da76b1d5b907fbe45dd4228e76df46138c6fc --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --all-groups --quiet && uv pip install --python .venv/bin/python coverage --quiet

# Default command: run tests
CMD ["bash", "-c", ".venv/bin/python -m pytest --tb=short -q"]
