FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/h2oai/h2o-llmstudio.git /app && \
    cd /app && (git checkout 751e7e7ed45d548e3e34adc5ac00ceefa18db164 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 751e7e7ed45d548e3e34adc5ac00ceefa18db164 && git checkout 751e7e7ed45d548e3e34adc5ac00ceefa18db164 --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv python install 3.10 && uv sync --dev --python 3.10

# Default command: run tests
CMD ["bash", "-c", "/app/.venv/bin/python -m pytest --tb=short -q --ignore=tests/ui --ignore=tests/integration"]
