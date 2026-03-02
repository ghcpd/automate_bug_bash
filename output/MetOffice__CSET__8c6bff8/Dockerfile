FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/MetOffice/CSET.git /app && \
    cd /app && (git checkout 8c6bff8854717a245320c33bcae417882f15b1c7 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 8c6bff8854717a245320c33bcae417882f15b1c7 && git checkout 8c6bff8854717a245320c33bcae417882f15b1c7 --quiet))
WORKDIR /app

# Install dependencies
RUN apt-get update -qq && apt-get install -y -qq graphviz libgraphviz-dev python3-dev pkg-config && sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && sed -i '/mo_pack/d' pyproject.toml && sed -i '/mo-pack/d' pyproject.toml && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . pytest pytest-cov pytest-xdist --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
