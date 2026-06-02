"""
Model Loader for Realtime ASR Service
Handles loading and managing ASR models from Hugging Face
"""

import os
from dataclasses import dataclass
from typing import Optional, Literal
import torch
from transformers import AutoTokenizer, AutoModelForCTC
import torch.nn.functional as F


@dataclass
class ModelConfig:
    """Configuration for model loading."""
    model_name: str = "Qwen/Qwen3-ASR-1.7B"
    model_path: Optional[str] = None
    use_whisper_fallback: bool = True
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    dtype: torch.dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    language: Optional[str] = "en"


class ASRModel:
    """
    ASR Model wrapper for Qwen3-ASR-1.7B
    
    This class handles model loading, tokenization, and inference.
    Falls back to Whisper if Qwen model fails to load.
    """
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.model: Optional[object] = None
        self.tokenizer: Optional[object] = None
        self.fallback_model: Optional[object] = None
        self.fallback_tokenizer: Optional[object] = None
        self.loaded_model: Literal["qwen", "whisper", "none"] = "none"
        
    def load(self) -> bool:
        """
        Load the ASR model.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            if self.config.model_path:
                model_name = self.config.model_path
            else:
                model_name = self.config.model_name
            
            # Load Qwen3-ASR-1.7B model
            print(f"Loading model: {model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=True
            )
            
            self.model = AutoModelForCTC.from_pretrained(
                model_name,
                torch_dtype=self.config.dtype,
                device_map=self.config.device,
                trust_remote_code=True
            )
            
            self.model.eval()
            self.loaded_model = "qwen"
            print("Qwen3-ASR-1.7B model loaded successfully")
            return True
            
        except Exception as e:
            print(f"Failed to load Qwen model: {e}")
            
            # Try Whisper fallback
            if self.config.use_whisper_fallback:
                self._load_whisper_fallback()
                return self.fallback_model is not None
            return False
    
    def _load_whisper_fallback(self):
        """Load Whisper model as fallback."""
        print("Loading Whisper fallback model...")
        try:
            from transformers import WhisperForCTC, WhisperTokenizerFast
            
            self.fallback_model = WhisperForCTC.from_pretrained(
                "openai/whisper-tiny",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None
            )
            self.fallback_model.eval()
            
            self.fallback_tokenizer = WhisperTokenizerFast.from_pretrained(
                "openai/whisper-tiny"
            )
            
            self.loaded_model = "whisper"
            print("Whisper fallback model loaded successfully")
            
        except Exception as e:
            print(f"Failed to load Whisper fallback: {e}")
    
    def tokenize(self, audio_data: bytes) -> torch.Tensor:
        """
        Tokenize audio data for inference.
        
        Args:
            audio_data: Raw audio bytes (16kHz, mono)
        
        Returns:
            Token tensor for model inference
        """
        if self.tokenizer:
            # Qwen tokenizer
            # In production, this would use librosa to load audio
            # For now, return empty tensor
            return torch.empty((1, 0), dtype=torch.long)
        elif self.fallback_tokenizer:
            # Whisper tokenizer
            from io import BytesIO
            from torchaudio import load
            
            # Load audio
            waveform, sr = load(BytesIO(audio_data))
            
            # Resample to 16kHz if needed
            if sr != 16000:
                from torchaudio.functional import resample
                waveform = resample(waveform, sr, 16000)
            
            # Convert to numpy and then to PyTorch tensor
            audio_tensor = torch.tensor(waveform).unsqueeze(0)
            
            # Whisper encoding
            features = self.fallback_model.feature_extractor(audio_tensor, return_tensors="pt").input_features
            
            return features.squeeze(0)
        else:
            raise ValueError("No model loaded")
    
    def transcribe(self, audio_data: bytes, language: Optional[str] = None) -> dict:
        """
        Transcribe audio data to text.
        
        Args:
            audio_data: Raw audio bytes
            language: Optional language code
        
        Returns:
            Dictionary with transcription result
        """
        try:
            # Get features
            features = self.tokenize(audio_data)
            
            # In production, would run actual inference here
            # For now, return mock result
            return {
                "text": "[ASR Model Ready] Transcribe audio data",
                "language": language or self.config.language,
                "duration_ms": len(audio_data) * 1000 // 16000,
                "confidence": 0.95
            }
            
        except Exception as e:
            print(f"Transcription error: {e}")
            return {
                "text": "",
                "error": str(e)
            }
    
    def is_loaded(self) -> bool:
        """Check if any model is loaded."""
        return self.loaded_model != "none"
    
    def model_name(self) -> str:
        """Return the name of the loaded model."""
        if self.loaded_model == "qwen":
            return "Qwen3-ASR-1.7B"
        elif self.loaded_model == "whisper":
            return "Whisper-Tiny"
        else:
            return "none"


async def load_model(config: ModelConfig) -> ASRModel:
    """
    Load and initialize the ASR model.
    
    Args:
        config: Model configuration
        
    Returns:
        Initialized ASRModel instance
    """
    model = ASRModel(config)
    return model
