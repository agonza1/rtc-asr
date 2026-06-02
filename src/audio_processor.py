"""
Audio Processor for Realtime ASR Service
Handles audio loading, resampling, chunking, and streaming
"""

import io
import numpy as np
from typing import Optional, Callable, AsyncGenerator
from dataclasses import dataclass
import time

import torchaudio
from torchaudio import transforms


@dataclass
class AudioConfig:
    """Configuration for audio processing."""
    sample_rate: int = 16000
    chunk_size: int = 1024  # 62.5ms at 16kHz
    max_latency_ms: int = 500
    device: str = "cuda" if True else "cpu"


class AudioProcessor:
    """
    Audio processor for real-time ASR.
    
    Handles:
    - Audio file loading (WAV, FLAC, MP3)
    - Audio resampling to target sample rate
    - Audio chunking for streaming
    - Buffer management for low-latency streaming
    """
    
    def __init__(self):
        self.config = AudioConfig()
        self._buffer: Optional[np.ndarray] = None
        self._buffer_index: int = 0
        self._session_start: float = 0
        
    def load_audio(self, audio_data: bytes) -> np.ndarray:
        """
        Load audio data from bytes.
        
        Args:
            audio_data: Raw audio bytes
        
        Returns:
            Audio waveform as numpy array
        """
        try:
            # Try different formats
            for extension in ['', '.wav', '.flac', '.ogg']:
                try:
                    tensor, sr = torchaudio.load(io.BytesIO(audio_data + b''))
                    
                    # Resample if needed
                    if sr != self.config.sample_rate:
                        from torchaudio.functional import resample
                        tensor = resample(tensor, sr, self.config.sample_rate)
                    
                    # Convert to numpy
                    audio = tensor.squeeze().numpy()
                    return audio
                    
                except Exception:
                    continue
            
            raise ValueError("Could not load audio file")
            
        except Exception as e:
            # Try base64 decoding if it looks like base64
            try:
                import base64
                # If it's already decoded, treat as raw audio
                audio = np.frombuffer(audio_data, dtype=np.float32)
                # Normalize
                audio = audio / np.max(np.abs(audio)) if np.max(np.abs(audio)) > 0 else audio
                return audio
            except:
                raise ValueError(f"Could not load audio: {e}")
    
    def transcribe(
        self,
        audio_data: bytes,
        model,
        language: Optional[str] = None
    ) -> dict:
        """
        Transcribe complete audio recording.
        
        Args:
            audio_data: Raw audio bytes
            model: ASR model instance
            language: Optional language code
        
        Returns:
            Transcription result
        """
        # Load and prepare audio
        audio = self.load_audio(audio_data)
        
        # In production, would call model.transcribe()
        # For now, return mock result
        return {
            "text": "[Transcription] This is a mock transcription",
            "language": language,
            "confidence": 0.92,
            "duration_ms": len(audio) * 1000 // self.config.sample_rate
        }
    
    def transcribe_chunk(
        self,
        audio_data: bytes,
        model,
        language: Optional[str] = None,
        session: Optional[dict] = None
    ) -> dict:
        """
        Process a single audio chunk.
        
        Args:
            audio_data: Raw audio chunk bytes
            model: ASR model instance
            language: Optional language code
            session: Optional session state
        
        Returns:
            Partial transcription result
        """
        # In production, this would:
        # 1. Add chunk to buffer
        # 2. Run inference on buffer
        # 3. Return partial text
        # 4. Clear buffer
        
        return {
            "partial_text": "",
            "confidence": 0.95
        }
    
    async def stream_transcribe(
        self,
        audio_data: bytes,
        model,
        language: Optional[str] = None,
        on_chunk: Optional[Callable] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Stream transcription for real-time audio.
        
        Args:
            audio_data: Raw audio bytes (streaming)
            model: ASR model instance
            language: Optional language code
            on_chunk: Optional callback for each chunk
        
        Yields:
            Partial transcription results
        """
        # Initialize session
        self._buffer = np.zeros(0)
        self._buffer_index = 0
        
        chunk_index = 0
        start_time = time.time()
        
        # In production, would process stream in chunks
        # For now, yield welcome message
        yield {
            "type": "welcome",
            "message": "Streaming transcription started",
            "language": language
        }
        
        # In production loop:
        # while chunk:
        #     yield self._process_chunk(chunk)
        
        # Simulate completion
        yield {
            "type": "complete",
            "text": "[Stream Complete] This is a mock completion",
            "duration_ms": int((time.time() - start_time) * 1000)
        }
    
    def flush_buffer(self) -> Optional[str]:
        """
        Flush and return any buffered audio.
        
        Returns:
            Text transcription or None
        """
        if self._buffer is not None and len(self._buffer) > 0:
            # In production, would run inference on buffer
            text = "[Flushed buffer] This is a mock flush result"
            
            # Reset buffer
            self._buffer = np.zeros(0)
            self._buffer_index = 0
            
            return text
        return None
    
    def get_buffer_state(self) -> dict:
        """Get current buffer state."""
        if self._buffer is None:
            return {
                "samples": 0,
                "duration_ms": 0
            }
        
        return {
            "samples": len(self._buffer),
            "duration_ms": len(self._buffer) * 1000 // self.config.sample_rate,
            "samples_to_flush": len(self._buffer) * self.config.sample_rate // 16000
        }
    
    def cleanup(self):
        """Clean up resources."""
        self._buffer = None
        self._buffer_index = 0
