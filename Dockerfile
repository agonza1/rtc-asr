FROM python:3.11-slim

ARG ENABLE_PARAKEET_RUNTIME=""

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
RUN grep -v '^torch$' requirements.txt > requirements.docker.txt && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    /opt/venv/bin/pip install -r requirements.docker.txt && \
    if [ -n "$ENABLE_PARAKEET_RUNTIME" ]; then /opt/venv/bin/pip install --upgrade --no-deps huggingface-hub==1.18.0 transformers==5.10.2; fi

COPY src ./src
COPY config.example ./

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD curl -fsS http://localhost:8080/ready || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
