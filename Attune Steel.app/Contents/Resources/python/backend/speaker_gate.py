"""
Speaker Gate — segment-level speaker verification before buffering.

Moves speaker verification UPSTREAM: verifies ~1.2-second segments of VAD-positive
audio BEFORE they enter the main SpeechBuffer. Only verified speech accumulates.

Features:
  - Sandwich recovery: borderline rejects between two verified segments are retroactively accepted
  - Momentum: after 3 consecutive verified segments, threshold lowers to 0.30 for sustained speech

Flow:
  1. Orchestrator feeds VAD-positive chunks to SpeakerGate.add_chunk()
  2. SpeakerGate accumulates a mini-buffer (~1.2s of speech)
  3. When mini-buffer fills, a worker thread runs ECAPA verification
  4. If verified: flushes chunks to on_verified_callback (→ SpeechBuffer)
  5. If borderline reject after verified: holds as pending (sandwich candidate)
  6. If next segment verifies and pending exists: retroactively accepts pending
  7. If hard reject: discards chunks
"""
import logging
import queue
import threading
import time
import numpy as np
from collections import deque
from datetime import datetime
from typing import Optional, Callable
import app_config as config

logger = logging.getLogger('attune.speaker_gate')


class SpeakerGate:
    def __init__(self, speaker_verifier, sample_rate: int = config.SAMPLE_RATE,
                 on_verified_callback: Optional[Callable] = None):
        """
        Args:
            speaker_verifier: SpeakerVerifier instance (must have verify_segment())
            sample_rate: Audio sample rate (16kHz)
            on_verified_callback: Called with (chunk, vad_confidence) for each
                                  verified chunk to pass to SpeechBuffer
        """
        self.speaker_verifier = speaker_verifier
        self.sample_rate = sample_rate
        self.on_verified_callback = on_verified_callback

        # Overlap detector (pitch-based multi-speaker detection)
        self._overlap_detector = None
        if config.OVERLAP_DETECTION_ENABLED:
            try:
                from backend.overlap_detector import OverlapDetector
                self._overlap_detector = OverlapDetector(sample_rate=sample_rate)
            except Exception as e:
                logger.warning(f"Overlap detector init failed: {e}")

        self.segment_samples = int(config.SPEAKER_GATE_SEGMENT_SEC * sample_rate)

        # Mini-buffer: accumulates chunks until segment_samples reached
        self._chunks: deque = deque()  # (audio_chunk, vad_confidence) tuples
        self._total_samples = 0
        self._segment_start_time: Optional[float] = None  # Wall-clock time of first chunk in segment
        self._min_speech_samples = int(config.SPEAKER_GATE_MIN_SPEECH_SEC * sample_rate)
        self._lock = threading.Lock()

        # Worker thread for verification (non-blocking)
        # TS-005: queue.get already uses timeout=0.05 (see _verify_worker)
        self._verify_queue: queue.Queue = queue.Queue(maxsize=50)
        self._worker_stop = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._verify_worker, daemon=True, name="speaker-gate-worker"
        )
        self._worker_thread.start()
        logger.debug("Speaker gate worker thread started")

        # Sandwich/continuity recovery state
        self._pending_reject = None       # (segment_chunks, similarity) held for one cycle
        self._last_verified = False       # Whether the previous segment was verified

        # Momentum / adaptive threshold state
        self._consecutive_verified = 0
        self._consecutive_rejected = 0
        self._momentum_active = False

        # Stats (protected by _stats_lock for cross-thread reads)
        self._stats_lock = threading.Lock()
        self._stats = {
            'segments_verified': 0,
            'segments_rejected': 0,
            'segments_sandwich_recovered': 0,
            'last_similarity': None,
        }
        self._recent_events: deque = deque(maxlen=20)

    def add_chunk(self, audio_chunk: np.ndarray, vad_confidence: float = 1.0):
        """Add a VAD-positive audio chunk. Non-blocking.

        If mini-buffer reaches segment threshold OR wall-clock timeout expires
        (with minimum speech), queues for verification.
        """
        with self._lock:
            self._chunks.append((audio_chunk, vad_confidence))
            self._total_samples += len(audio_chunk)

            # Record wall-clock time when first chunk enters an empty mini-buffer
            if self._segment_start_time is None:
                self._segment_start_time = time.time()

            # Trigger verification if:
            # 1. Full speech segment accumulated (original behavior), OR
            # 2. Wall-clock timeout exceeded AND minimum speech collected
            wall_elapsed = time.time() - self._segment_start_time
            trigger = (
                self._total_samples >= self.segment_samples
                or (wall_elapsed >= config.SPEAKER_GATE_MAX_WALL_SEC
                    and self._total_samples >= self._min_speech_samples)
            )

            if trigger:
                # Drain mini-buffer into a segment for verification
                segment_chunks = list(self._chunks)
                self._chunks.clear()
                self._total_samples = 0
                self._segment_start_time = None

                # Queue for async verification (bounded to prevent memory growth)
                try:
                    self._verify_queue.put_nowait(segment_chunks)
                except queue.Full:
                    # Drop oldest segment to make room
                    try:
                        self._verify_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._verify_queue.put_nowait(segment_chunks)
                    except queue.Full:
                        pass
                    logger.warning("Speaker gate queue full, dropped oldest segment")

    def _verify_worker(self):
        """Background worker that verifies queued segments.
        TS-005: queue.get uses timeout so thread wakes regularly to check stop event.
        TS-003: Logs thread lifecycle for diagnostics."""
        logger.debug("Speaker gate verify worker running")
        while not self._worker_stop.is_set():
            try:
                segment_chunks = self._verify_queue.get(timeout=0.5)
                self._verify_segment(segment_chunks)
            except queue.Empty:
                continue
        logger.debug("Speaker gate verify worker stopped")

    def _verify_segment(self, segment_chunks):
        """Run ECAPA verification on a segment with sandwich recovery and momentum."""
        # Concatenate audio for verification
        audio_arrays = [chunk for chunk, _ in segment_chunks]
        segment_audio = np.concatenate(audio_arrays)
        dur = len(segment_audio) / self.sample_rate

        # --- Overlap detection (before ECAPA, saves compute) ---
        if self._overlap_detector is not None:
            try:
                if self._overlap_detector.detect_overlap(segment_audio):
                    self._last_verified = False
                    self._consecutive_rejected += 1
                    self._consecutive_verified = 0
                    if self._consecutive_rejected >= config.SPEAKER_GATE_MOMENTUM_DECAY and self._momentum_active:
                        self._momentum_active = False
                    self._pending_reject = None
                    with self._stats_lock:
                        self._stats['segments_rejected'] += 1
                        self._recent_events.append({
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'duration': round(dur, 1),
                            'similarity': 0.0,
                            'verified': False,
                            'overlap_rejected': True,
                        })
                    logger.debug(f"Overlap-rejected segment ({dur:.1f}s)")
                    return
            except Exception as e:
                logger.debug(f"Overlap check error (continuing): {e}")

        # Duration-compensated threshold: short segments (from wall-clock timeout)
        # produce noisier ECAPA embeddings, so we linearly interpolate the threshold
        # between momentum floor (at min speech) and normal threshold (at full segment).
        target_dur = config.SPEAKER_GATE_SEGMENT_SEC
        min_dur = config.SPEAKER_GATE_MIN_SPEECH_SEC
        if dur < target_dur and target_dur > min_dur:
            ratio = max(0.0, min(1.0, (dur - min_dur) / (target_dur - min_dur)))
            effective_threshold = (config.SPEAKER_GATE_MOMENTUM_THRESHOLD
                                   + ratio * (config.SPEAKER_GATE_THRESHOLD
                                              - config.SPEAKER_GATE_MOMENTUM_THRESHOLD))
        else:
            effective_threshold = None  # Full-length segment → use default from config

        try:
            verified, similarity = self.speaker_verifier.verify_segment(
                segment_audio, threshold=effective_threshold
            )
        except Exception as e:
            logger.error(f"Verification error: {e}, passing through")
            verified = True
            similarity = -1.0

        # Post-hoc momentum: if rejected at default threshold but momentum is active
        # and similarity >= MOMENTUM_MIN_SIM, re-evaluate with lowered threshold
        if not verified and self._momentum_active and similarity >= config.SPEAKER_GATE_MOMENTUM_MIN_SIM:
            verified = similarity >= config.SPEAKER_GATE_MOMENTUM_THRESHOLD

        with self._stats_lock:
            self._stats['last_similarity'] = similarity
        tag = ""

        # --- Absolute floor early reject ---
        if similarity < config.SPEAKER_GATE_ABSOLUTE_FLOOR:
            self._pending_reject = None
            self._consecutive_rejected += 1
            self._consecutive_verified = 0
            if self._consecutive_rejected >= config.SPEAKER_GATE_MOMENTUM_DECAY and self._momentum_active:
                self._momentum_active = False
                logger.info(f"Momentum deactivated (threshold -> {config.SPEAKER_GATE_THRESHOLD})")
            self._last_verified = False
            with self._stats_lock:
                self._stats['segments_rejected'] += 1
                self._recent_events.append({
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'duration': round(dur, 1),
                    'similarity': round(float(similarity), 3),
                    'verified': False,
                    'momentum': self._momentum_active,
                    'floor_rejected': True,
                })
            logger.debug(f"Floor-rejected segment ({dur:.1f}s, similarity={similarity:.3f} < {config.SPEAKER_GATE_ABSOLUTE_FLOOR})")
            return

        # --- Sandwich/continuity recovery ---
        # If current segment verifies AND there's a pending reject with borderline similarity,
        # retroactively accept the pending reject (it was sandwiched between two verified)
        if verified and self._pending_reject is not None:
            pending_chunks, pending_sim = self._pending_reject
            if pending_sim >= config.SPEAKER_GATE_SANDWICH_THRESHOLD:
                # Recover the pending segment
                with self._stats_lock:
                    self._stats['segments_sandwich_recovered'] += 1
                    self._stats['segments_verified'] += 1
                    self._stats['segments_rejected'] -= 1  # Undo the earlier rejection count
                pending_dur = sum(len(c) for c, _ in pending_chunks) / self.sample_rate
                if self.on_verified_callback:
                    for chunk, confidence in pending_chunks:
                        self.on_verified_callback(chunk, confidence)
                logger.info(f"Sandwich-recovered pending segment ({pending_dur:.1f}s, similarity={pending_sim:.3f})")
                with self._stats_lock:
                    self._recent_events.append({
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'duration': round(pending_dur, 1),
                        'similarity': round(float(pending_sim), 3),
                        'verified': True,
                        'sandwich_recovered': True,
                    })
            self._pending_reject = None

        if not verified and similarity >= config.SPEAKER_GATE_SANDWICH_THRESHOLD and self._last_verified:
            # Borderline reject after a verified segment — hold as pending (might be sandwiched)
            if self._pending_reject is not None:
                # Already holding a pending — discard the old one
                pass
            self._pending_reject = (segment_chunks, similarity)
            tag = " [held-pending]"
        elif not verified:
            # Hard reject — also discard any pending
            self._pending_reject = None

        # --- Momentum tracking ---
        if verified:
            self._consecutive_verified += 1
            self._consecutive_rejected = 0
            if self._consecutive_verified >= config.SPEAKER_GATE_MOMENTUM_WINDOW and not self._momentum_active:
                self._momentum_active = True
                logger.info(f"Momentum activated (threshold -> {config.SPEAKER_GATE_MOMENTUM_THRESHOLD})")
        else:
            self._consecutive_rejected += 1
            self._consecutive_verified = 0
            if self._consecutive_rejected >= config.SPEAKER_GATE_MOMENTUM_DECAY and self._momentum_active:
                self._momentum_active = False
                logger.info(f"Momentum deactivated (threshold -> {config.SPEAKER_GATE_THRESHOLD})")

        # Record event for debug overlay
        with self._stats_lock:
            self._recent_events.append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'duration': round(dur, 1),
                'similarity': round(float(similarity), 3),
                'threshold_used': round(effective_threshold if effective_threshold is not None else config.SPEAKER_GATE_THRESHOLD, 3),
                'verified': verified,
                'momentum': self._momentum_active,
            })

        if verified:
            with self._stats_lock:
                self._stats['segments_verified'] += 1
            self._last_verified = True
            # Flush individual chunks to SpeechBuffer via callback
            if self.on_verified_callback:
                for chunk, confidence in segment_chunks:
                    self.on_verified_callback(chunk, confidence)

            momentum_tag = " [momentum]" if self._momentum_active else ""
            logger.debug(f"Verified segment ({dur:.1f}s, similarity={similarity:.3f}){momentum_tag}")
        else:
            with self._stats_lock:
                self._stats['segments_rejected'] += 1
            self._last_verified = False
            logger.debug(f"Rejected segment ({dur:.1f}s, similarity={similarity:.3f}){tag}")

    def flush_remaining(self):
        """Flush any remaining chunks in the mini-buffer (e.g., on stop).

        Remaining chunks are too short for reliable verification, so they're discarded.
        """
        with self._lock:
            remaining = self._total_samples / self.sample_rate
            if remaining > 0:
                logger.debug(f"Discarding {remaining:.1f}s remaining (too short to verify)")
            self._chunks.clear()
            self._total_samples = 0
            self._segment_start_time = None

    def stop(self):
        """Stop the worker thread.
        TS-003: Signals stop event and joins with timeout."""
        self._worker_stop.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
            if self._worker_thread.is_alive():
                logger.warning("Speaker gate worker thread did not stop within timeout")
        self.flush_remaining()
        logger.debug("Speaker gate stopped")

    def get_stats(self) -> dict:
        """Get gate statistics (thread-safe snapshot)."""
        with self._stats_lock:
            stats_copy = dict(self._stats)
            events_copy = list(self._recent_events)
            momentum = self._momentum_active
        total = stats_copy['segments_verified'] + stats_copy['segments_rejected']
        return {
            'segments_verified': stats_copy['segments_verified'],
            'segments_rejected': stats_copy['segments_rejected'],
            'segments_sandwich_recovered': stats_copy['segments_sandwich_recovered'],
            'total_segments': total,
            'pass_rate': (stats_copy['segments_verified'] / total * 100) if total > 0 else 0,
            'last_similarity': stats_copy['last_similarity'],
            'momentum_active': momentum,
            'recent_events': events_copy,
        }
