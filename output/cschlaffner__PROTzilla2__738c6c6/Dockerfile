FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/cschlaffner/PROTzilla2.git /app && \
    cd /app && (git checkout 738c6c6045fe72fa1d69856548a893bdff65d84a --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 738c6c6045fe72fa1d69856548a893bdff65d84a && git checkout 738c6c6045fe72fa1d69856548a893bdff65d84a --quiet))
WORKDIR /app

# Install dependencies
RUN uv python install 3.11 && uv venv /opt/venv --python 3.11 --quiet --clear && uv pip install --python /opt/venv/bin/python -r requirements.txt --quiet && uv pip install --python /opt/venv/bin/python 'setuptools<71' --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
