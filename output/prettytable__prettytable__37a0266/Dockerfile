FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/prettytable/prettytable.git /app && \
    cd /app && (git checkout 37a02661a7fab52d4d2db613ffeda44ea928ae60 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 37a02661a7fab52d4d2db613ffeda44ea928ae60 && git checkout 37a02661a7fab52d4d2db613ffeda44ea928ae60 --quiet))
WORKDIR /app

# Install dependencies
RUN cd /app && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e '.[tests]' --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=no -q"]
