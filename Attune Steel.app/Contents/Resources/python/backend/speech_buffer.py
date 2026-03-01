"""
Speech buffer that accumulates speech segments and triggers analysis.

Two-tier trigger system:
  - Soft trigger at 30s: starts grace period, keeps accumulating
  - Hard trigger at 60s: optimal DAM reliability
  - Force trigger at 90s: max buffer
  - Grace timeout: if speech stops for >grace_period after soft trigger, analyze

Also tracks VAD confidence per chunk for quality gating.

Thread-safety: all buffer mutations protected by _lock.
Trigger callback runs OUTSIDE lock to avoid blocking chunk delivery.
"""
import logging
import threading
import time
import numpy as np
from collections import deque
from typing import Optional, Callable, Tuple
import app_config as config

logger = logging.getLogger('attune.speech_buffer')


class SpeechBuffer:
    def __init__(self,
                 sample_rate: int = config.SAMPLE_RATE,
                 threshold_sec: int = config.SPEECH_THRESHOLD_SEC,
                 preferred_sec: int = config.PREFERRED_SPEECH_SEC,
                 max_buffer_sec: int = config.BUFFER_SIZE_SEC,
                 grace_period_sec: int = config.GRACE_PERIOD_SEC,
                 on_threshold_callback: Optional[Callable] = None):
        """
        Args:
            sample_rate: Audio sample rate
            threshold_sec: Soft trigger threshold (30s)
            preferred_sec: Hard trigger threshold (60s, optimal)
            max_buffer_sec: Maximum buffer size before force-trigger (90s)
            grace_period_sec: Grace period after soft trigger (15s)
            on_threshold_callback: Function to call when analysis should run
        """
        self.sample_rate = sample_rate
        self.threshold_samples = threshold_sec * sample_rate
        self.preferred_samples = preferred_sec * sample_rate
        self.max_buffer_samples = max_buffer_sec * sample_rate
        self.grace_period_sec = grace_period_sec
        self.on_threshold_callback = on_threshold_callback

        self.speech_chunks: deque = deque(maxlen=3000)  # (chunk, confidence) tuples
        self.total_speech_samples = 0

        # Grace period tracking
        self._soft_triggered = False
        self._last_chunk_time: float = 0.0

        # Thread safety lock
        self._lock = threading.Lock()

    def add_speech_chunk(self, chunk: np.ndarray, vad_confidence: float = 1.0):
        """
        Add a chunk of speech audio to the buffer with VAD confidence.

        Args:
            chunk: numpy array of speech samples
            vad_confidence: VAD speech probability (0-1)
        """
        with self._lock:
            self.speech_chunks.append((chunk, vad_confidence))
            self.total_speech_samples += len(chunk)
            self._last_chunk_time = time.monotonic()

        # Trigger checks OUTSIDE lock (callback may take time)
        self._check_triggers()

    def _check_triggers(self):
        """Check if any trigger threshold is met. Called after every chunk add."""
        with self._lock:
            samples = self.total_speech_samples
            soft = self._soft_triggered

        # Hard trigger at preferred duration (60s) — optimal reliability
        if samples >= self.preferred_samples:
            logger.info(f"Preferred duration reached ({config.PREFERRED_SPEECH_SEC}s)")
            self._trigger_analysis()
            return

        # Force trigger at max buffer (90s)
        if samples >= self.max_buffer_samples:
            logger.info(f"Max buffer reached ({config.BUFFER_SIZE_SEC}s), force-triggering")
            self._trigger_analysis()
            return

        # Soft trigger at threshold (30s) — start grace period
        if samples >= self.threshold_samples and not soft:
            with self._lock:
                self._soft_triggered = True
            logger.info(f"Soft trigger at {config.SPEECH_THRESHOLD_SEC}s, "
                        f"grace period {self.grace_period_sec}s")

    def check_grace_timeout(self):
        """
        Check if grace period has expired (speech stopped after soft trigger).
        Call this periodically from the orchestrator.
        """
        with self._lock:
            if not self._soft_triggered:
                return
            if self.total_speech_samples == 0:
                return
            elapsed = time.monotonic() - self._last_chunk_time
            grace = self.grace_period_sec
            total = self.total_speech_samples
            sr = self.sample_rate

        if elapsed >= grace:
            duration = total / sr
            logger.info(f"Grace timeout ({elapsed:.1f}s silence), "
                        f"analyzing {duration:.1f}s of speech")
            self._trigger_analysis()

    def _trigger_analysis(self):
        """Atomic snapshot-then-clear: grab buffer contents and clear under lock,
        then invoke callback outside lock so it doesn't block chunk delivery."""
        with self._lock:
            if not self.on_threshold_callback or self.total_speech_samples == 0:
                return

            # Snapshot
            chunks = [c for c, _ in self.speech_chunks]
            confidences = [conf for _, conf in self.speech_chunks]
            speech_audio = np.concatenate(chunks)
            duration_sec = len(speech_audio) / self.sample_rate
            mean_vad_confidence = float(np.mean(confidences)) if confidences else 1.0

            logger.info(f"Triggering analysis with {duration_sec:.1f}s of speech "
                        f"(VAD confidence: {mean_vad_confidence:.2f})")

            # Clear buffer INSIDE lock (atomic snapshot + clear)
            self._do_clear()

        # Callback OUTSIDE lock (non-blocking for buffer)
        self.on_threshold_callback(speech_audio, duration_sec, mean_vad_confidence)

    def _do_clear(self):
        """Internal clear (must be called with _lock held)."""
        self.speech_chunks.clear()
        self.total_speech_samples = 0
        self._soft_triggered = False
        self._last_chunk_time = 0.0

    def clear(self):
        """Clear the buffer (thread-safe)."""
        with self._lock:
            self._do_clear()

    def get_current_duration(self) -> float:
        """Get current buffered speech duration in seconds"""
        with self._lock:
            return self.total_speech_samples / self.sample_rate

    def get_mean_confidence(self) -> float:
        """Get mean VAD confidence of buffered chunks"""
        with self._lock:
            if not self.speech_chunks:
                return 0.0
            return float(np.mean([conf for _, conf in self.speech_chunks]))

    def is_ready(self) -> bool:
        """Check if buffer has reached soft threshold"""
        with self._lock:
            return self.total_speech_samples >= self.threshold_samples
