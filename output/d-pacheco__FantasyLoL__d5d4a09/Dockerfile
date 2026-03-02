FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/d-pacheco/FantasyLoL.git /app && \
    cd /app && (git checkout d5d4a0984217de1205bea70efe7fae7cb4120e72 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin d5d4a0984217de1205bea70efe7fae7cb4120e72 && git checkout d5d4a0984217de1205bea70efe7fae7cb4120e72 --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -r requirements-base.txt -r requirements-dev.txt pytest --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
