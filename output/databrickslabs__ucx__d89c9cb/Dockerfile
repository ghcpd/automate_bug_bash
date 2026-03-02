FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/databrickslabs/ucx.git /app && \
    cd /app && (git checkout d89c9cb924fba70b03cbebe51c85cab85a2f9dfc --quiet 2>/dev/null || \
    (git fetch --depth=1 origin d89c9cb924fba70b03cbebe51c85cab85a2f9dfc && git checkout d89c9cb924fba70b03cbebe51c85cab85a2f9dfc --quiet))
WORKDIR /app

# Install dependencies
RUN sed -i '/^required-version/d' pyproject.toml 2>/dev/null; true && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e . --quiet && uv pip install --python /opt/venv/bin/python 'pytest~=8.3.3' 'pytest-cov~=4.1.0' 'pytest-mock~=3.14.0' 'pytest-timeout~=2.3.1' 'pytest-xdist~=3.5.0' 'databricks-labs-pytester>=0.7.2' 'python-lsp-server>=1.9.0' --quiet && rm -rf /app/.venv && ln -s /opt/venv /app/.venv

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
