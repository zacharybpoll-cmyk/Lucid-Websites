"""
Voice Activity Detection using Silero VAD
Classifies audio chunks as speech or silence
"""
import logging
import torch
import numpy as np
from typing import Tuple
import app_config as config

logger = logging.getLogger('lucid.vad')


class VADProcessor:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.model = None
        self._load_model()

    def _load_model(self):
        """Load Silero VAD model"""
        try:
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            self.model = model
            self.get_speech_timestamps = utils[0]
            logger.info("Silero VAD model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading Silero VAD model: {e}")
            raise

    def is_speech(self, audio_chunk: np.ndarray) -> Tuple[bool, float]:
        """
        Classify a single audio chunk as speech or silence

        Args:
            audio_chunk: numpy array of audio samples (16kHz, mono)

        Returns:
            Tuple of (is_speech: bool, confidence: float)
        """
        if self.model is None:
            return False, 0.0

        try:
            # Convert to torch tensor — Silero VAD v5 expects 1D tensor for single chunks
            audio_tensor = torch.from_numpy(audio_chunk).float()

            # Get speech probability
            with torch.no_grad():
                speech_prob = self.model(audio_tensor, self.sample_rate).item()

            # Threshold (configurable, default was 0.5)
            is_speech = speech_prob > config.VAD_SPEECH_THRESHOLD

            return is_speech, speech_prob

        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            return False, 0.0

    def get_speech_segments(self, audio: np.ndarray) -> list:
        """
        Get speech timestamp segments from longer audio

        Args:
            audio: numpy array of audio samples

        Returns:
            List of dicts with 'start' and 'end' timestamps in samples
        """
        if self.model is None:
            return []

        try:
            audio_tensor = torch.from_numpy(audio).float()
            speech_timestamps = self.get_speech_timestamps(
                audio_tensor,
                self.model,
                sampling_rate=self.sample_rate,
                threshold=config.VAD_SPEECH_THRESHOLD,
                min_speech_duration_ms=250,
                min_silence_duration_ms=100
            )
            return speech_timestamps
        except Exception as e:
            logger.error(f"Error getting speech segments: {e}")
            return []
