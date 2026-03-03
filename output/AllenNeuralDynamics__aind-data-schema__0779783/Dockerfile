FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/AllenNeuralDynamics/aind-data-schema.git /app && \
    cd /app && (git checkout 077978381fd7f91c7c683ceea0fe9f6e37149cbf --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 077978381fd7f91c7c683ceea0fe9f6e37149cbf && git checkout 077978381fd7f91c7c683ceea0fe9f6e37149cbf --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[dev]" pytest --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
