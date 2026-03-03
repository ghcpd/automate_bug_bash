FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/agoenergy/ptx-boa.git /app && \
    cd /app && (git checkout 8c098c50d7b55190f9659ae2cf9f69a8bd4ff8b2 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 8c098c50d7b55190f9659ae2cf9f69a8bd4ff8b2 && git checkout 8c098c50d7b55190f9659ae2cf9f69a8bd4ff8b2 --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && { uv pip install --python /opt/venv/bin/python -r requirements-dev.txt --quiet 2>/dev/null; true; } && uv pip install --python /opt/venv/bin/python -r requirements.txt --quiet && uv pip install --python /opt/venv/bin/python pytest --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
