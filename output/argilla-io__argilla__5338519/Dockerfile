FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/argilla-io/argilla.git /app && \
    cd /app && (git checkout 5338519accb13ae422f8bf9c0642651c249c49af --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 5338519accb13ae422f8bf9c0642651c249c49af && git checkout 5338519accb13ae422f8bf9c0642651c249c49af --quiet))
WORKDIR /app

# Install dependencies
RUN cd /app/argilla && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e '.[dev]' --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-mock pytest-httpx pyarrow markdown --quiet

# Default command: run tests
CMD ["bash", "-c", "cd /app/argilla && /opt/venv/bin/python -m pytest tests/unit --tb=short -q"]
