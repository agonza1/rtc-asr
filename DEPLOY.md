# Deployment Guide

This guide covers deploying the Realtime ASR Service to production environments.

## Prerequisites

- Docker and Docker Compose installed
- GPU-enabled host (recommended) or CPU-only environment
- 16GB+ RAM
- Port 8080 available

## Quick Deployment

```bash
# Build image
docker compose build

# Start service
docker compose up -d

# Check status
docker compose ps
docker compose logs -f
```

## Production Configuration

### Environment Variables

Create `.env.production`:

```env
# Model Configuration
MODEL_NAME=Qwen3-ASR-1.7B
USE_WHISPER_FALLBACK=true

# Service Configuration
HOST=0.0.0.0
PORT=8080

# Audio Configuration
SAMPLE_RATE=16000
CHUNK_SIZE=1024
BUFFER_SIZE=2

# GPU Configuration
CUDA_VISIBLE_DEVICES=0
GPU_MEMORY_FRACTION=0.8

# Security
ASR_API_KEY=your-api-key
ASR_API_SECRET=your-api-secret

# CORS
CORS_ORIGINS=https://yourdomain.com,*

# Logging
LOG_LEVEL=info
LOG_FORMAT=json
```

### Docker Compose Production

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  asr:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        MODEL_NAME: ${MODEL_NAME}
    image: realtime-asr:latest
    container_name: realtime-asr
    environment:
      - MODEL_NAME=${MODEL_NAME}
      - USE_WHISPER_FALLBACK=${USE_WHISPER_FALLBACK:-false}
      - ASR_API_KEY=${ASR_API_KEY}
      - ASR_API_SECRET=${ASR_API_SECRET}
    ports:
      - "8080:8080"
    volumes:
      - asr-models:/models
      - ./config:/config:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
        limits:
          cpus: ${CPU_LIMIT:-4}
          memory: ${MEMORY_LIMIT:-8G}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    restart: unless-stopped

volumes:
  asr-models:
```

## Cloud Deployment

### AWS EC2

```bash
# SSH to instance
ssh -i key.pem ec2-user@instance.ip

# Install Docker
sudo yum install docker
sudo systemctl start docker
sudo systemctl enable docker

# Clone repository
git clone https://github.com/qwen/realtime-asr.git
cd realtime-asr

# Configure
cp .env.example .env.production
vim .env.production

# Build and run
docker compose -f docker-compose.prod.yml up -d

# Verify
curl http://instance.ip:8080/health
```

### AWS Lambda (Serverless)

```python
# lambda_function.py
import json
import base64
import boto3
import requests

def lambda_handler(event, context):
    # Invoke ASR service
    response = requests.post(
        'http://your-asr-service:8080/api/transcribe',
        json=event['body']
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps(response.json())
    }
```

### Kubernetes

```yaml
# deployment.yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: realtime-asr
spec:
  replicas: 2
  selector:
    matchLabels:
      app: realtime-asr
  template:
    metadata:
      labels:
        app: realtime-asr
    spec:
      containers:
      - name: asr
        image: realtime-asr:latest
        ports:
        - containerPort: 8080
        env:
        - name: MODEL_NAME
          value: "Qwen3-ASR-1.7B"
        resources:
          limits:
            memory: "4Gi"
            cpu: "1"
          requests:
            memory: "2Gi"
            cpu: "500m"
        volumeMounts:
        - name: models
          mountPath: /models
      volumes:
      - name: models
        emptyDir: {}
```

## Monitoring Setup

### Prometheus

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'asr'
    static_configs:
      - targets: ['asr:8080']
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Realtime ASR Metrics",
    "panels": [
      {
        "title": "Request Latency",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(asr_latency_bucket[5m]))"
          }
        ]
      },
      {
        "title": "Active Connections",
        "targets": [
          {
            "expr": "asr_connections_active"
          }
        ]
      }
    ]
  }
}
```

## Security Hardening

### 1. Network Policies

```yaml
# k8s network-policy.yml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-asr-traffic
spec:
  podSelector:
    matchLabels:
      app: realtime-asr
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
```

### 2. Rate Limiting

```python
# In FastAPI app
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(CORSMiddleware, allow_origins=["*"])

# Rate limiter
from slowapi import RateLimiter
from slowapi.util import get_remote_address

app.state.rate_limiter = RateLimiter(
    allowed_requests=100,
    period=60,
    key_func=get_remote_address
)
```

### 3. Secrets Management

```bash
# Use env vars or Kubernetes Secrets
kubectl create secret generic asr-secrets \
  --from-literal=api-key=your-key \
  --from-literal=api-secret=your-secret
```

## Backup Strategy

### 1. Model Backup

```bash
# Backup models
docker save realtime-asr > asr-model.tar.gz

# Restore
docker load < asr-model.tar.gz
```

### 2. Configuration Backup

```bash
# Backup configuration
tar -czf config-backup.tar.gz config/
```

### 3. Automated Backup

```bash
#!/bin/bash
# backup.sh
BACKUP_DIR=/backup/asr
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

docker save realtime-asr | gzip > ${BACKUP_DIR}/models-${TIMESTAMP}.tar.gz
tar -czf ${BACKUP_DIR}/config-${TIMESTAMP}.tar.gz config/

# Clean old backups
find ${BACKUP_DIR} -name "*.tar.gz" -mtime +7 -delete
```

## Scaling Strategy

### Horizontal Scaling

```bash
# Scale replicas
docker compose scale asr=5

# Load balancer
haproxy -f /etc/haproxy/haproxy.cfg -D
```

### Vertical Scaling

```yaml
# Increase resources
resources:
  limits:
    memory: "8Gi"
    cpu: "2"
  requests:
    memory: "4Gi"
    cpu: "1"
```

## Health Checks

```bash
# Basic health check
curl http://localhost:8080/health

# Detailed health check
curl http://localhost:8080/api/metrics

# WebSocket health check
timeout 5 bash -c 'echo | nc localhost 8080'
```

## Rollback Strategy

```bash
# Scale back to stable version
docker compose scale asr=0

# Pull old image
docker pull realtime-asr:v0.9.0

# Scale new version
docker compose scale asr=1
```

## Performance Tuning

### 1. GPU Optimization

```bash
# Pin GPU memory
nvidia-smi -i 0 -pm 1 -ac 1 -ldc 0 -lc 0

# Set memory fraction
export CUDA_MEMORY_FRACTION=0.8
```

### 2. Network Optimization

```bash
# Use fast storage
mke2fs -t xfs /dev/sdX

# Enable SSD cache
echo 1 > /proc/sys/vm/vfs_cache_pressure
```

## Troubleshooting Deployment

### Service Won't Start

```bash
# Check logs
docker logs realtime-asr

# Check health
docker inspect realtime-asr | grep Health

# Verify resources
docker stats
```

### High Memory Usage

```bash
# Increase memory limit
docker update --memory=8g realtime-asr

# Check model loading
docker compose exec asr python -c "import torch; print(torch.cuda.memory_allocated())"
```

### WebSocket Connection Issues

```bash
# Check WebSocket endpoint
curl -v ws://localhost:8080/ws/stream

# Check server logs
docker logs | grep -i websocket
```

## Next Steps

- [Setup Guide](./setup.md)
- [API Reference](./api-reference.md)
- [Integration Guides](./integrations.md)
- [Monitoring Setup](./monitoring.md)

## Support

- Email: support@qwen.ai
- GitHub: https://github.com/qwen/realtime-asr
- Slack: https://qwen.ai/slack
