# Realtime ASR Service - Dockerfile
# Multi-stage build for optimized runtime image

# Stage 1: Build environment
FROM nvidia/cuda:12.4.1-cudnn9-devel-ubuntu22.04 AS builder

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

WORKDIR /app

# Create virtual environment
RUN python3.11 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ /app/src/
COPY templates/ /app/templates/

# Stage 2: Runtime image
FROM nvidia/cuda:12.4.1-cudnn9-devel-ubuntu22.04 AS runtime

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Setup virtual environment
RUN python3.11 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy requirements and install
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY --from=builder /app/src /app/src
COPY --from=builder /app/templates /app/templates

WORKDIR /app

# Copy model (this will be mounted externally in production)
COPY --chown=app:app model_loader.py config/ /app/

# Create non-root user
RUN useradd -m -g app app && chown -R app:app /app
USER app

EXPOSE 8080

CMD ["python", "-m", "src.main"]
