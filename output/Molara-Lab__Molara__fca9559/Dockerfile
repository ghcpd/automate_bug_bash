FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/Molara-Lab/Molara.git /app && \
    cd /app && (git checkout fca95593eaf298f082ab8e83f2d7aba32babbe0c --quiet 2>/dev/null || \
    (git fetch --depth=1 origin fca95593eaf298f082ab8e83f2d7aba32babbe0c && git checkout fca95593eaf298f082ab8e83f2d7aba32babbe0c --quiet))
WORKDIR /app

# Install dependencies
RUN apt-get update -qq && apt-get install -y -qq python3-dev build-essential libgl1-mesa-dev libxkbcommon-x11-0 libglib2.0-0 libegl1 libxcb-xinerama0 libxcb-cursor0 xvfb libfontconfig1 libdbus-1-3 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -e ".[tests]" --quiet

# Default command: run tests
CMD ["bash", "-c", "/opt/venv/bin/python -m pytest --tb=short -q"]
