FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/getsentry/sentry-python.git /app && \
    cd /app && (git checkout c11d1f2f23899ed3511d478b30ea24777222c274 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin c11d1f2f23899ed3511d478b30ea24777222c274 && git checkout c11d1f2f23899ed3511d478b30ea24777222c274 --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[pure-eval]" --quiet && uv pip install --python /opt/venv/bin/python -r requirements-testing.txt --quiet && uv pip install --python /opt/venv/bin/python pytest-asyncio --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest tests/ --tb=short -q --override-ini='addopts=' --ignore=tests/integrations"]
