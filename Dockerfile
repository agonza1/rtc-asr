ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ARG ENABLE_PARAKEET_RUNTIME=""
ARG ENABLE_NEMO_RUNTIME=""
ARG ENABLE_PIPECAT_DEMO_RUNTIME=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /opt/venv

COPY requirements.txt ./
COPY examples/browser_pipecat_demo/requirements.txt ./examples/browser_pipecat_demo/requirements.txt
RUN grep -v '^torch$' requirements.txt > requirements.docker.txt && \
    if [ -n "$ENABLE_NEMO_RUNTIME" ]; then grep -Ev '^(torch|qwen-asr|transformers==|accelerate|faster-whisper|pytest|httpx)' requirements.txt > requirements.docker.txt; fi && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    /opt/venv/bin/pip install -r requirements.docker.txt && \
    if [ -n "$ENABLE_PIPECAT_DEMO_RUNTIME" ]; then /opt/venv/bin/pip install -r examples/browser_pipecat_demo/requirements.txt; fi && \
    if [ -n "$ENABLE_PARAKEET_RUNTIME" ]; then /opt/venv/bin/pip install --upgrade --no-deps huggingface-hub==1.18.0 transformers==5.10.2; fi && \
    if [ -n "$ENABLE_NEMO_RUNTIME" ]; then /opt/venv/bin/pip install 'nemo_toolkit[asr]>=2.2.0'; fi

COPY src ./src
COPY examples ./examples
COPY config.example ./

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD if [ "$LOCAL_STT_SOCKET_MODE" = uds ]; then curl -fsS --unix-socket "${LOCAL_STT_UDS_PATH:-/run/rtc-asr/stt.sock}" http://localhost/ready; else curl -fsS http://localhost:8080/ready; fi

CMD ["python", "-m", "src.main"]
