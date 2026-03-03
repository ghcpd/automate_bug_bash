FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/fractal-analytics-platform/fractal-tasks-core.git /app && \
    cd /app && (git checkout c9578d96a710043f9de6b9dcbb41a53bd4388cbd --quiet 2>/dev/null || \
    (git fetch --depth=1 origin c9578d96a710043f9de6b9dcbb41a53bd4388cbd && git checkout c9578d96a710043f9de6b9dcbb41a53bd4388cbd --quiet))
WORKDIR /app

# Install dependencies
RUN uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python pytest devtools coverage jsonschema requests pooch --quiet && uv pip install --python /opt/venv/bin/python /app/tests/data/napari_workflows/mock_package/dist/napari_skimage_regionprops_mock-9.9.9-py3-none-any.whl --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --ignore=tests/tasks --tb=short -q"]
