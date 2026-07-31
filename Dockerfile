# syntax=docker/dockerfile:1.7
ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE} AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_CACHE_DIR=/root/.cache/pip \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /opt/venv

FROM python-base AS asr-common

COPY requirements.txt ./
COPY requirements/docker-common.txt ./requirements/docker-common.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements/docker-common.txt

COPY src ./src
COPY examples ./examples
COPY config.example ./

FROM asr-common AS asr-faster-whisper-cpu

COPY requirements/docker-faster-whisper.txt ./requirements/docker-faster-whisper.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install -r requirements/docker-faster-whisper.txt

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/.cache/huggingface && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD if [ "$LOCAL_STT_SOCKET_MODE" = uds ]; then curl -fsS --unix-socket "${LOCAL_STT_UDS_PATH:-/run/rtc-asr/stt.sock}" http://localhost/ready; else curl -fsS http://localhost:8080/ready; fi

CMD ["python", "-m", "src.main"]

FROM asr-common AS asr-qwen-cpu

COPY requirements/docker-qwen.txt ./requirements/docker-qwen.txt
COPY requirements/docker-torch-cpu.txt ./requirements/docker-torch-cpu.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu -r requirements/docker-torch-cpu.txt && \
    /opt/venv/bin/pip install -r requirements/docker-qwen.txt

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/.cache/huggingface && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD if [ "$LOCAL_STT_SOCKET_MODE" = uds ]; then curl -fsS --unix-socket "${LOCAL_STT_UDS_PATH:-/run/rtc-asr/stt.sock}" http://localhost/ready; else curl -fsS http://localhost:8080/ready; fi

CMD ["python", "-m", "src.main"]

FROM asr-common AS asr-parakeet-transformers-cpu

COPY requirements/docker-parakeet-transformers.txt ./requirements/docker-parakeet-transformers.txt
COPY requirements/docker-torch-cpu.txt ./requirements/docker-torch-cpu.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu -r requirements/docker-torch-cpu.txt && \
    /opt/venv/bin/pip install --upgrade --no-deps -r requirements/docker-parakeet-transformers.txt

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/.cache/huggingface && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD if [ "$LOCAL_STT_SOCKET_MODE" = uds ]; then curl -fsS --unix-socket "${LOCAL_STT_UDS_PATH:-/run/rtc-asr/stt.sock}" http://localhost/ready; else curl -fsS http://localhost:8080/ready; fi

CMD ["python", "-m", "src.main"]

FROM asr-common AS asr-parakeet-nemo-cpu

COPY requirements/docker-parakeet-nemo.txt ./requirements/docker-parakeet-nemo.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install -r requirements/docker-parakeet-nemo.txt

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app/.cache/huggingface && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD if [ "$LOCAL_STT_SOCKET_MODE" = uds ]; then curl -fsS --unix-socket "${LOCAL_STT_UDS_PATH:-/run/rtc-asr/stt.sock}" http://localhost/ready; else curl -fsS http://localhost:8080/ready; fi

CMD ["python", "-m", "src.main"]

FROM python-base AS browser-pipecat-demo

COPY examples/browser_pipecat_demo/requirements.txt ./examples/browser_pipecat_demo/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r examples/browser_pipecat_demo/requirements.txt

COPY src ./src
COPY examples ./examples

RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /run/rtc-asr && \
    chown -R app:app /app /run/rtc-asr
USER app

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8090/rtc-asr/config

CMD ["uvicorn", "examples.browser_pipecat_demo.service.app:app", "--host", "0.0.0.0", "--port", "8090"]

FROM asr-faster-whisper-cpu AS runtime
