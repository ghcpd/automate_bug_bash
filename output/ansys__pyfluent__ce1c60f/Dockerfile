FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/ansys/pyfluent.git /app && \
    cd /app && (git checkout ce1c60f276e2f0db0cf76f4913ec9f7e3713f18e --quiet 2>/dev/null || \
    (git fetch --depth=1 origin ce1c60f276e2f0db0cf76f4913ec9f7e3713f18e && git checkout ce1c60f276e2f0db0cf76f4913ec9f7e3713f18e --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[tests,reader]" --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q --ignore=tests/test_field_data.py --ignore=tests/test_settings_api.py"]
