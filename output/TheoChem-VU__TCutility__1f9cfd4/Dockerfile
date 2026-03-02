FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/TheoChem-VU/TCutility.git /app && \
    cd /app && (git checkout 1f9cfd4dd6b9e0c5d0e97f209b974897a9b567b6 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 1f9cfd4dd6b9e0c5d0e97f209b974897a9b567b6 && git checkout 1f9cfd4dd6b9e0c5d0e97f209b974897a9b567b6 --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[dev,analysis,vdd]" --quiet && uv pip install --python /opt/venv/bin/python filelock --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
