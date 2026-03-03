FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/dstackai/dstack.git /app && \
    cd /app && (git checkout 9eea926fd68f2fefae60de1a342e1e70f3d91220 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 9eea926fd68f2fefae60de1a342e1e70f3d91220 && git checkout 9eea926fd68f2fefae60de1a342e1e70f3d91220 --quiet))
WORKDIR /app

# Install dependencies
RUN cd /app && sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv sync --group dev

# Default command: run tests
CMD ["bash", "-c", "/app/.venv/bin/python -m pytest --tb=short -q"]
