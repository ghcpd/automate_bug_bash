FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/scikit-hep/awkward.git /app && \
    cd /app && (git checkout a6c3b25c36a40732c20b45313f8b705b94e1fc2d --quiet 2>/dev/null || \
    (git fetch --depth=1 origin a6c3b25c36a40732c20b45313f8b705b94e1fc2d && git checkout a6c3b25c36a40732c20b45313f8b705b94e1fc2d --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python awkward-cpp==52 --quiet && uv pip install --python /opt/venv/bin/python -e /app --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-xdist --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
