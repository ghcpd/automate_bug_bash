FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/meltano/sdk.git /app && \
    cd /app && (git checkout 8b6fe9925d3eb3aa88938fa3bf0c96c52e328745 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 8b6fe9925d3eb3aa88938fa3bf0c96c52e328745 && git checkout 8b6fe9925d3eb3aa88938fa3bf0c96c52e328745 --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --group testing --no-group dev --extra faker --extra jwt

# Default command: run tests
CMD ["bash", "-c", "/app/.venv/bin/python -m pytest --tb=short -q --ignore=tests/external --ignore=tests/packages --ignore=tests/contrib/encoding/test_msgspec.py"]
