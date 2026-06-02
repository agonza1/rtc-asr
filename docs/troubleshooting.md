# Troubleshooting Guide

This guide helps you resolve common issues with the Realtime ASR Service.

## Quick Start

1. **Service won't start**
   ```bash
   docker logs realtime-asr
   ```

2. **Check health**
   ```bash
   curl http://localhost:8080/health
   ```

3. **Restart service**
   ```bash
   docker compose restart
   ```

## Common Issues

### 1. Service Won't Start

**Symptoms:**
- `docker compose up` fails immediately
- Error: `ERROR: Cannot start service`

**Solutions:**

1. **Check Docker:**
   ```bash
   docker --version
   docker info
   ```

2. **Check Port 8080:**
   ```bash
   lsof -i :8080
   # Kill any process using port 8080
   ```

3. **Check Disk Space:**
   ```bash
   df -h
   # Free up space if < 10GB available
   ```

4. **Check Logs:**
   ```bash
   docker compose logs
   docker compose logs -f
   ```

### 2. Model Loading Failure

**Symptoms:**
- Error: `Failed to load model`
- Error: `OSError: Could not find model`

**Solutions:**

1. **Verify Model Path:**
   ```bash
   ls -la /models/Qwen3-ASR-1.7B
   ```

2. **Check Model Exists:**
   ```bash
   docker compose exec asr-service ls models/Qwen3-ASR-1.7B
   ```

3. **Download Model:**
   ```bash
   docker compose exec asr-service python -c "from model_loader import load_model, ModelConfig; c=ModelConfig(); c.model_name='Qwen/Qwen3-ASR-1.7B'; c.load()"
   ```

4. **Use Fallback:**
   ```bash
   # In .env, set USE_WHISPER_FALLBACK=true
   ```

### 3. Audio Format Error

**Symptoms:**
- Error: `Invalid audio format`
- Error: `Could not decode audio`

**Solutions:**

1. **Check Sample Rate:**
   ```bash
   soxi -r recording.wav
   # Should be 16000 Hz
   ```

2. **Convert Audio:**
   ```bash
   sox recording.wav -r 16000 -c 1 converted.wav
   ```

3. **Check Channels:**
   ```bash
   # Should be mono (1 channel)
   ```

### 4. High Latency

**Symptoms:**
- P99 latency > 1000ms
- Users complain about delay

**Solutions:**

1. **Enable GPU:**
   ```bash
   docker run --gpus all ...
   ```

2. **Reduce Chunk Size:**
   ```env
   AUDIO_CHUNK_SIZE=512  # 31.25ms
   ```

3. **Use WebSocket:**
   ```python
   # Connect to /ws/stream instead of REST
   ```

4. **Enable Model Warmup:**
   ```bash
   WARMUP_MODEL=true
   ```

### 5. Connection Timeout

**Symptoms:**
- Error: `Connection timed out`
- Error: `Max retries exceeded`

**Solutions:**

1. **Check Network:**
   ```bash
   ping localhost
   curl localhost:8080/health
   ```

2. **Check Firewall:**
   ```bash
   # Allow port 8080
   sudo ufw allow 8080/tcp
   ```

3. **Increase Timeout:**
   ```env
   REQUEST_TIMEOUT=30
   ```

### 6. Memory Issues

**Symptoms:**
- Error: `CUDA out of memory`
- Error: `Killed` in logs

**Solutions:**

1. **Check Memory:**
   ```bash
   docker stats
   ```

2. **Reduce Batch Size:**
   ```env
   BATCH_SIZE=1
   ```

3. **Use CPU:**
   ```env
   CUDA_VISIBLE_DEVICES=""
   ```

4. **Increase RAM:**
   ```bash
   # Allocate more memory to Docker
   ```

### 7. WebSocket Connection Issues

**Symptoms:**
- Error: `Connection refused`
- Error: `WebSocket handshake failed`

**Solutions:**

1. **Check WebSocket Endpoint:**
   ```bash
   curl -v ws://localhost:8080/ws/stream
   ```

2. **Enable CORS:**
   ```env
   CORS_ORIGINS=*
   ```

3. **Increase Buffer:**
   ```python
   # In client code
   ws.protocol = ws.create_protocol('WebSocket')
   ws.binary_type = bytes
   ```

### 8. Language Detection Errors

**Symptoms:**
- Wrong language detected
- Transcription in wrong language

**Solutions:**

1. **Specify Language:**
   ```json
   {
     "language": "en"
   }
   ```

2. **Use Language Model:**
   ```bash
   # In config
   DEFAULT_LANGUAGE=en
   ```

3. **Check Language Support:**
   ```bash
   curl http://localhost:8080/api/models
   ```

### 9. Authentication Errors

**Symptoms:**
- Error: `401 Unauthorized`
- Error: `Invalid API key`

**Solutions:**

1. **Set API Key:**
   ```bash
   export ASR_API_KEY=your-key
   ```

2. **Add to Headers:**
   ```python
   headers = {
       "Authorization": f"Bearer {api_key}"
   }
   ```

### 10. Performance Degradation

**Symptoms:**
- Slow responses
- High memory usage

**Solutions:**

1. **Check Model Loading:**
   ```bash
   docker logs | grep "Model loaded"
   ```

2. **Restart Service:**
   ```bash
   docker compose restart
   ```

3. **Clear Cache:**
   ```bash
   docker compose exec asr-service python -c "import torch; torch.cuda.empty_cache()"
   ```

4. **Monitor Resources:**
   ```bash
   docker stats
   ```

## Debugging Commands

### View Logs

```bash
# All logs
docker compose logs -f

# Specific service
docker compose logs -f asr-service

# Last 100 lines
docker compose logs --tail=100
```

### Exec into Container

```bash
# Run command
docker compose exec asr-service bash

# Install packages
docker compose exec asr-service pip install package

# Check model
docker compose exec asr-service python -c "import torch; print(torch.__version__)"
```

### Debug Mode

```bash
docker compose down
LOG_LEVEL=debug docker compose up -d
```

### Clear Cache

```bash
docker compose down
docker volume rm realtime-asr-cached-models
docker compose up -d
```

## Performance Tuning

### 1. GPU Tuning

```bash
# Use specific GPU
CUDA_VISIBLE_DEVICES=0,1 docker run ...

# Pin GPU memory
--gpus '"device=0:all"'
```

### 2. CPU Tuning

```bash
# Use multiple cores
docker run --cpus=4 ...

# Pin to cores
--cpuset-cpus=0-7
```

### 3. Memory Tuning

```bash
# Limit memory
-m 4g

# Increase swap
--memory-swap=8g
```

## Monitoring

### Check Health

```bash
curl http://localhost:8080/health
```

### Check Metrics

```bash
curl http://localhost:8080/api/metrics
```

### Check Resource Usage

```bash
docker stats --no-stream
```

## Escalation

If issue persists:

1. **Collect Logs:**
   ```bash
   docker compose logs > logs.txt
   ```

2. **Collect Config:**
   ```bash
   docker compose config > config.txt
   ```

3. **Collect Metrics:**
   ```bash
   curl http://localhost:8080/api/metrics > metrics.txt
   ```

4. **Create Issue:**
   ```bash
   # Include all files in bug report
   ```

## Resources

- [GitHub Issues](https://github.com/qwen/realtime-asr/issues)
- [Qwen Model Documentation](https://github.com/QwenLM/Qwen3-ASR-1.7B)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PyTorch Documentation](https://pytorch.org/docs/)

## Support

For commercial support, contact:
- Email: support@qwen.ai
- Slack: https://qwen.ai/slack

---

## Prevention Tips

1. **Use Health Checks:**
   ```yaml
   # docker-compose.yml
   healthcheck:
     test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
     interval: 30s
     timeout: 10s
     retries: 3
   ```

2. **Monitor Metrics:**
   ```bash
   # Set up monitoring
   prometheus pushgateway ...
   ```

3. **Automate Alerts:**
   ```yaml
   # Alert on high latency
   latency_p99 > 1000
   ```

4. **Regular Updates:**
   ```bash
   # Update model weekly
   docker pull realtime-asr:latest
   ```
