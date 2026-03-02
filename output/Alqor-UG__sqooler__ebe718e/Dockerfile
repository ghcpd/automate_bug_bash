FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/Alqor-UG/sqooler.git /app && \
    cd /app && (git checkout ebe718e9d26112474b324f0e026152a2a53d00b8 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin ebe718e9d26112474b324f0e026152a2a53d00b8 && git checkout ebe718e9d26112474b324f0e026152a2a53d00b8 --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest pytest-cov python-decouple icecream --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
