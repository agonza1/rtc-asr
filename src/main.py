#!/usr/bin/env python3
"""
Realtime ASR Service - Main entry point
Provides REST and WebSocket endpoints for real-time speech recognition
"""

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from model_loader import load_model, ModelConfig
from audio_processor import AudioProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Realtime ASR Service",
    description="Low-latency speech-to-text using Qwen3-ASR-1.7B",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
model: Optional[object] = None
audio_processor: Optional[AudioProcessor] = None


async def initialize():
    """Initialize models and processors."""
    global model, audio_processor
    
    logger.info("Initializing ASR service...")
    
    config = ModelConfig()
    model = load_model(config)
    audio_processor = AudioProcessor()
    
    logger.info("ASR service initialized successfully")
    return True


# ============================================================================
# REST Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "realtime-asr"}


@app.get("/api/models")
async def list_models():
    """List available models."""
    return {
        "models": ["Qwen3-ASR-1.7B"],
        "languages": ["en", "es", "fr", "de", "zh", "ja", "ko", "it"],
        "sample_rate": 16000,
        "latency_ms": "<500ms"
    }


@app.post("/api/transcribe")
async def transcribe_audio(
    audio_data: str,
    language: str = "en",
    sample_rate: int = 16000,
    stream: bool = False
):
    """
    Transcribe audio data.
    
    Args:
        audio_data: Base64 encoded audio data
        language: Language code (en, es, fr, de, zh, etc.)
        sample_rate: Audio sample rate in Hz
        stream: Whether to use streaming mode
    
    Returns:
        Transcription result
    """
    if not model:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        # Decode audio data
        audio_bytes = base64.b64decode(audio_data)
        
        # Process transcription
        if stream:
            result = await audio_processor.stream_transcribe(
                audio_bytes,
                model=model,
                language=language
            )
            return result
        else:
            result = await audio_processor.transcribe(
                audio_bytes,
                model=model,
                language=language
            )
            return result
            
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transcribe/file")
async def transcribe_file(
    file: UploadFile,
    language: str = "en",
    sample_rate: int = 16000
):
    """Transcribe audio file."""
    if not model:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    try:
        content = await file.read()
        
        result = await audio_processor.transcribe(
            content,
            model=model,
            language=language
        )
        
        return {
            "filename": file.filename,
            "transcription": result
        }
        
    except Exception as e:
        logger.error(f"File transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stream")
async def stream_transcribe(
    audio_chunk: dict
):
    """
    Streaming transcription endpoint.
    
    Expects:
    {
        "audio": "base64_data",
        "chunk_index": 0
    }
    
    Returns partial transcription results
    """
    if not model:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        audio_data = base64.b64decode(audio_chunk["audio"])
        
        # In production, this would maintain state for the session
        # For now, process as individual chunk
        result = await audio_processor.transcribe_chunk(
            audio_data,
            model=model,
            language="en"
        )
        
        return {
            "chunk": audio_chunk["chunk_index"],
            "partial_text": result.get("partial_text", ""),
            "final_text": result.get("text", "")
        }
        
    except Exception as e:
        logger.error(f"Stream chunk error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# WebSocket Endpoints
# ============================================================================

@app.websocket("/ws/stream")
async def websocket_stream(websocket):
    """
    WebSocket endpoint for real-time streaming transcription.
    
    Protocol:
    - Client sends audio chunks as binary or base64
    - Server sends partial results as WebSocket messages
    """
    if not model:
        await websocket.close(code=503)
        return
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "welcome",
            "message": "Connected to ASR stream",
            "status": "ready"
        })
        
        # Process incoming audio chunks
        chunk_index = 0
        
        async for receive_data in websocket.iter_text():
            try:
                message = json.loads(receive_data)
                message_type = message.get("type", "audio")
                
                if message_type == "audio":
                    # Process audio chunk
                    audio_data = base64.b64decode(message["audio"])
                    
                    # In production, maintain session state for chunked processing
                    result = await audio_processor.transcribe_chunk(
                        audio_data,
                        model=model,
                        language=message.get("language", "en")
                    )
                    
                    await websocket.send_json({
                        "type": "partial",
                        "chunk": chunk_index,
                        "text": result.get("partial_text", ""),
                        "confidence": result.get("confidence", 0.0)
                    })
                    
                    chunk_index += 1
                    
                elif message_type == "flush":
                    # Request to flush partial results
                    await websocket.send_json({
                        "type": "flush",
                        "text": result.get("text", "")
                    })
                    
            except json.JSONDecodeError:
                # Might be binary audio data
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON, expecting audio chunk or flush command"
                })
                
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Main application entry point."""
    await initialize()
    
    host = Path("config").joinpath(".env") if Path("config").exists() else None
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        workers=1,
        log_level="info"
    )


if __name__ == "__main__":
    asyncio.run(main())
