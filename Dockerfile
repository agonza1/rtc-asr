ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ARG ENABLE_PARAKEET_RUNTIME=""
ARG ENABLE_NEMO_RUNTIME=""
ARG ENABLE_PIPECAT_DEMO_RUNTIME=""
ARG ENABLE_QWEN_RUNTIME=""

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
COPY requirements/docker-common.txt ./requirements/docker-common.txt
COPY requirements/docker-faster-whisper.txt ./requirements/docker-faster-whisper.txt
COPY requirements/docker-parakeet-nemo.txt ./requirements/docker-parakeet-nemo.txt
COPY requirements/docker-parakeet-transformers.txt ./requirements/docker-parakeet-transformers.txt
COPY requirements/docker-qwen.txt ./requirements/docker-qwen.txt
COPY requirements/docker-torch-cpu.txt ./requirements/docker-torch-cpu.txt
COPY examples/browser_pipecat_demo/requirements.txt ./examples/browser_pipecat_demo/requirements.txt
RUN /opt/venv/bin/pip install --upgrade pip && \
    if [ -n "$ENABLE_PIPECAT_DEMO_RUNTIME" ]; then \
      /opt/venv/bin/pip install -r examples/browser_pipecat_demo/requirements.txt; \
    else \
      /opt/venv/bin/pip install -r requirements/docker-common.txt && \
      if [ -n "$ENABLE_QWEN_RUNTIME" ]; then /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu -r requirements/docker-torch-cpu.txt && /opt/venv/bin/pip install -r requirements/docker-qwen.txt; fi && \
      if [ -n "$ENABLE_PARAKEET_RUNTIME" ]; then /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu -r requirements/docker-torch-cpu.txt && /opt/venv/bin/pip install --upgrade --no-deps -r requirements/docker-parakeet-transformers.txt; fi && \
      if [ -z "$ENABLE_QWEN_RUNTIME" ] && [ -z "$ENABLE_PARAKEET_RUNTIME" ] && [ -z "$ENABLE_NEMO_RUNTIME" ]; then /opt/venv/bin/pip install -r requirements/docker-faster-whisper.txt; fi && \
      if [ -n "$ENABLE_NEMO_RUNTIME" ]; then /opt/venv/bin/pip install -r requirements/docker-parakeet-nemo.txt; fi; \
    fi

COPY src ./src
COPY examples ./examples
COPY config.example ./

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/.cache/huggingface && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD if [ "$LOCAL_STT_SOCKET_MODE" = uds ]; then curl -fsS --unix-socket "${LOCAL_STT_UDS_PATH:-/run/rtc-asr/stt.sock}" http://localhost/ready; else curl -fsS http://localhost:8080/ready; fi

CMD ["python", "-m", "src.main"]
