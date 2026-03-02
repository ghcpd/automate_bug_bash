FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/cfpb/sbl-filing-api.git /app && \
    cd /app && (git checkout 395fa9ce80f655557d13a71394361661f7ab0d53 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 395fa9ce80f655557d13a71394361661f7ab0d53 && git checkout 395fa9ce80f655557d13a71394361661f7ab0d53 --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python poetry && /opt/venv/bin/poetry install --with dev

# Default command: run tests
CMD ["bash", "-c", "/app/.venv/bin/python -m pytest --tb=short -q"]
