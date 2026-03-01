"""
Speaker verification using SpeechBrain ECAPA-TDNN.
Identifies the enrolled user's voice and rejects other speakers.

Flow:
  1. Enrollment: user records 3 x 10s samples (neutral, animated, calm)
     → 3 embeddings → centroid stored in DB
  2. Verification: each speech buffer → embedding → cosine similarity vs centroid
     → accept (>= threshold) or reject
  3. Adaptive update: high-confidence verifications slowly drift centroid via EMA
"""
import logging
import os
import time
import tempfile
import subprocess
import numpy as np
import torch
import torchaudio
import huggingface_hub
import threading
from typing import Tuple, Optional, List
from collections import deque
from pathlib import Path
import app_config as config

logger = logging.getLogger('attune.speaker')

# Patch torchaudio compatibility for speechbrain (torchaudio 2.10+ removed list_audio_backends)
if not hasattr(torchaudio, 'list_audio_backends'):
    torchaudio.list_audio_backends = lambda: []

# Patch huggingface_hub compatibility for speechbrain (deprecated use_auth_token param)
_original_hf_download = huggingface_hub.hf_hub_download
def _patched_hf_download(*args, **kwargs):
    kwargs.pop('use_auth_token', None)
    return _original_hf_download(*args, **kwargs)
huggingface_hub.hf_hub_download = _patched_hf_download


class SpeakerVerifier:
    def __init__(self, db=None):
        self.db = db
        self.model = None
        self._lock = threading.Lock()
        self._centroid: Optional[np.ndarray] = None
        self._enrollment_centroid: Optional[np.ndarray] = None
        self._enrollment_embeddings: List[np.ndarray] = []
        self._enrolled = False
        self.threshold = config.SPEAKER_VERIFICATION_THRESHOLD
        # PLDA scorer (optional)
        self._plda_scorer = None
        # Windowed adaptation state
        self._verified_window: List[Tuple[np.ndarray, float]] = []  # (embedding, similarity)
        self._max_window_size = 50
        self._consecutive_failures = 0
        self._last_verification_ts: Optional[float] = None

    def load_model(self):
        """Load ECAPA-TDNN model from SpeechBrain. Call from background thread."""
        from speechbrain.inference.speaker import EncoderClassifier

        speaker_cache_env = os.environ.get('ATTUNE_SPEAKER_CACHE_DIR')
        cache_dir = Path(speaker_cache_env) if speaker_cache_env else (config.DATA_DIR / "speaker_model")
        cache_dir.mkdir(exist_ok=True)

        # Create placeholder custom.py (this model has no custom modules, but
        # SpeechBrain's from_hparams tries to fetch it and fails on 404)
        custom_py = cache_dir / "custom.py"
        if not custom_py.exists():
            custom_py.write_text("# Placeholder — this model has no custom modules\n")

        logger.info("Loading ECAPA-TDNN model...")
        self.model = EncoderClassifier.from_hparams(
            source=config.SPEAKER_MODEL_SOURCE,
            savedir=str(cache_dir),
            run_opts={"device": "cpu"},
        )
        logger.info("ECAPA-TDNN model loaded")

        # Optionally load PLDA scorer
        if config.PLDA_ENABLED:
            try:
                from backend.plda_scorer import PLDAScorer
                self._plda_scorer = PLDAScorer()
                if not self._plda_scorer.load_model(str(config.PLDA_MODEL_PATH)):
                    self._plda_scorer = None
            except Exception as e:
                logger.warning(f"PLDA scorer init failed: {e}")
                self._plda_scorer = None

        # Load stored voiceprint if exists
        self._load_profile()

    # Expected embedding dimension from ECAPA-TDNN (lin_neurons: 192)
    EXPECTED_EMBEDDING_DIM = 192

    def _load_profile(self):
        """Load voiceprint from database if enrolled."""
        if self.db is None:
            return
        profile = self.db.get_speaker_profile()
        if profile and profile.get('embedding') is not None:
            self._centroid = np.frombuffer(profile['embedding'], dtype=np.float32).copy()

            # Load enrollment embeddings first (needed for dimension repair)
            samples = self.db.get_enrollment_samples()
            if samples:
                self._enrollment_embeddings = []
                for s in samples:
                    emb = np.frombuffer(s['embedding'], dtype=np.float32).copy()
                    self._enrollment_embeddings.append(emb)

            # Dimension validation: detect corrupted centroid (e.g. 384-dim instead of 192)
            expected_dim = self.EXPECTED_EMBEDDING_DIM
            if self._enrollment_embeddings:
                expected_dim = self._enrollment_embeddings[0].shape[0]

            if self._centroid.shape[0] != expected_dim:
                logger.warning(
                    f"Centroid dimension mismatch: {self._centroid.shape[0]} vs expected {expected_dim}. "
                    f"Re-deriving centroid from {len(self._enrollment_embeddings)} enrollment samples."
                )
                if self._enrollment_embeddings:
                    centroid = np.mean(self._enrollment_embeddings, axis=0)
                    norm = np.linalg.norm(centroid)
                    if norm > 0:
                        centroid = centroid / norm
                    self._centroid = centroid
                    # Persist the corrected centroid
                    if self.db:
                        self.db.update_speaker_centroid(self._centroid.tobytes())
                    logger.info(f"Centroid repaired: now {self._centroid.shape[0]}-dim")
                else:
                    logger.error("Cannot repair centroid — no enrollment samples available")
                    self._enrolled = False
                    return

            self._enrollment_centroid = self._centroid.copy()
            self._enrolled = True
            # Load adaptive threshold if stored
            stored_threshold = profile.get('similarity_threshold')
            if stored_threshold and stored_threshold > 0:
                self.threshold = stored_threshold
                logger.info(f"Loaded voiceprint ({self._centroid.shape[0]}-dim, adaptive threshold={self.threshold:.3f})")
            else:
                logger.info(f"Loaded voiceprint ({self._centroid.shape[0]}-dim)")
            if self._enrollment_embeddings:
                logger.info(f"Loaded {len(self._enrollment_embeddings)} enrollment embeddings for multi-centroid")
        else:
            self._enrolled = False

    def is_enrolled(self) -> bool:
        return self._enrolled

    def get_embedding(self, audio: np.ndarray) -> np.ndarray:
        """Extract 192-dim speaker embedding from audio.

        Args:
            audio: float32 numpy array, 16kHz mono, range [-1, 1]

        Returns:
            192-dim embedding vector (L2-normalized)
        """
        if self.model is None:
            raise RuntimeError("Speaker model not loaded")

        # Ensure float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Convert to torch tensor [1, num_samples]
        waveform = torch.from_numpy(audio).unsqueeze(0)

        with torch.no_grad():
            embedding = self.model.encode_batch(waveform)

        # Shape: [1, 1, 192] → [192]
        emb = embedding.squeeze().cpu().numpy()

        # L2 normalize
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm

        return emb

    def _apply_opus_codec(self, audio: np.ndarray, sr: int, bitrate_kbps: int) -> Optional[np.ndarray]:
        """Apply Opus codec roundtrip to simulate VoIP degradation.

        Returns codec-degraded audio, or None on failure.
        """
        try:
            import soundfile as sf
            with tempfile.TemporaryDirectory() as tmpdir:
                wav_in = f"{tmpdir}/in.wav"
                opus_out = f"{tmpdir}/out.opus"
                wav_out = f"{tmpdir}/out.wav"

                sf.write(wav_in, audio, sr, subtype='PCM_16')

                # Encode to Opus
                result = subprocess.run(
                    ['ffmpeg', '-y', '-i', wav_in, '-c:a', 'libopus',
                     '-b:a', f'{bitrate_kbps}k', '-ar', str(sr), opus_out],
                    capture_output=True, timeout=10
                )
                if result.returncode != 0:
                    return None

                # Decode back to WAV
                result = subprocess.run(
                    ['ffmpeg', '-y', '-i', opus_out, '-ar', str(sr), wav_out],
                    capture_output=True, timeout=10
                )
                if result.returncode != 0:
                    return None

                decoded, _ = sf.read(wav_out, dtype='float32')
                return decoded
        except Exception as e:
            logger.warning(f"Codec augmentation failed ({bitrate_kbps}kbps): {e}")
            return None

    def enroll_sample(self, audio: np.ndarray, mood_label: str) -> np.ndarray:
        """Process a single enrollment sample with optional codec augmentation.

        Args:
            audio: raw audio (float32, 16kHz)
            mood_label: 'neutral', 'animated', 'calm', 'reading', 'on_a_call',
                        'bootstrap', 'enhance_*'

        Returns:
            The embedding vector for this sample
        """
        embedding = self.get_embedding(audio)

        # Store in DB
        if self.db:
            duration = len(audio) / config.SAMPLE_RATE
            self.db.add_enrollment_sample(
                mood_label=mood_label,
                embedding=embedding.tobytes(),
                duration_sec=duration,
            )

        # Codec augmentation: skip for bootstrap/enhance (already diverse conditions)
        skip_codec = mood_label.startswith('bootstrap') or mood_label.startswith('enhance')
        if not skip_codec and self.db:
            for bitrate in [32, 16]:
                degraded = self._apply_opus_codec(audio, config.SAMPLE_RATE, bitrate)
                if degraded is not None:
                    codec_emb = self.get_embedding(degraded)
                    self.db.add_enrollment_sample(
                        mood_label=f"{mood_label}_codec{bitrate}",
                        embedding=codec_emb.tobytes(),
                        duration_sec=duration,
                    )
                    logger.debug(f"Added codec-{bitrate}kbps variant for {mood_label}")

        return embedding

    def complete_enrollment(self) -> np.ndarray:
        """Compute centroid from all enrollment samples and activate verification.

        Returns:
            The centroid embedding
        """
        if self.db is None:
            raise RuntimeError("Database required for enrollment")

        samples = self.db.get_enrollment_samples()
        if not samples:
            raise ValueError("No enrollment samples found")

        # Compute centroid (mean of L2-normalized embeddings)
        embeddings = []
        for s in samples:
            emb = np.frombuffer(s['embedding'], dtype=np.float32).copy()
            embeddings.append(emb)

        centroid = np.mean(embeddings, axis=0)
        # Re-normalize
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm

        # Compute adaptive threshold from pairwise similarities
        if len(embeddings) >= 2:
            pairwise_sims = []
            for i in range(len(embeddings)):
                for j in range(i + 1, len(embeddings)):
                    pairwise_sims.append(float(np.dot(embeddings[i], embeddings[j])))
            min_pairwise = min(pairwise_sims)
            adaptive_threshold = max(config.SPEAKER_VERIFICATION_THRESHOLD, min_pairwise - 0.05)
            self.threshold = adaptive_threshold
            logger.info(f"Adaptive threshold: {adaptive_threshold:.3f} (min pairwise={min_pairwise:.3f})")
        else:
            adaptive_threshold = self.threshold

        with self._lock:
            self._centroid = centroid
            self._enrollment_centroid = centroid.copy()
            self._enrollment_embeddings = list(embeddings)
            self._enrolled = True

        # Save profile to DB
        self.db.save_speaker_profile(
            embedding=centroid.tobytes(),
            embedding_dim=len(centroid),
            num_samples=len(embeddings),
            threshold=self.threshold,
        )

        logger.info(f"Enrollment complete — {len(embeddings)} samples -> centroid")
        return centroid

    def _compute_similarity(self, embedding: np.ndarray) -> float:
        """Compute max similarity across centroid and all enrollment embeddings.

        Uses PLDA scoring when available, falling back to cosine similarity.
        """
        # Try PLDA first
        if self._plda_scorer is not None and self._plda_scorer.is_loaded and self._enrollment_embeddings:
            plda_score = self._plda_scorer.score(self._enrollment_embeddings, embedding)
            if plda_score is not None:
                return plda_score

        # Cosine similarity fallback (multi-centroid)
        with self._lock:
            # Dimension safety check
            if embedding.shape[0] != self._centroid.shape[0]:
                logger.error(
                    f"Similarity computation failed: embedding dim {embedding.shape[0]} "
                    f"!= centroid dim {self._centroid.shape[0]}"
                )
                return -1.0

            centroid_sim = float(np.dot(embedding, self._centroid))
            if self._enrollment_embeddings:
                max_enroll_sim = max(
                    float(np.dot(embedding, e))
                    for e in self._enrollment_embeddings
                    if e.shape[0] == embedding.shape[0]
                )
                return max(centroid_sim, max_enroll_sim)
            return centroid_sim

    def verify(self, audio: np.ndarray) -> Tuple[bool, float]:
        """Verify if audio belongs to the enrolled speaker.

        Args:
            audio: speech segment (float32, 16kHz)

        Returns:
            (is_verified, similarity_score)
        """
        if not self._enrolled or self._centroid is None:
            return True, 1.0  # No profile → pass through

        # Apply stale bias if no verification in 24h
        self._apply_stale_bias()

        embedding = self.get_embedding(audio)
        similarity = self._compute_similarity(embedding)

        is_verified = similarity >= self.threshold

        if is_verified:
            self._consecutive_failures = 0
            self._last_verification_ts = time.time()
            # Adaptive centroid update for high-confidence matches
            if similarity >= config.SPEAKER_HIGH_CONFIDENCE:
                self._update_centroid(embedding, similarity)
        else:
            self._handle_verification_failure()

        return is_verified, similarity

    def verify_segment(self, audio: np.ndarray, threshold: float = None) -> Tuple[bool, float]:
        """Verify a short segment without adaptive centroid update.

        Used by SpeakerGate for segment-level verification before buffering.

        Args:
            audio: short speech segment (float32, 16kHz, ~2s)
            threshold: override threshold (defaults to SPEAKER_GATE_THRESHOLD)

        Returns:
            (is_verified, similarity_score)
        """
        if not self._enrolled or self._centroid is None:
            return True, 1.0  # No profile → pass through

        if threshold is None:
            threshold = self.threshold

        embedding = self.get_embedding(audio)
        similarity = self._compute_similarity(embedding)

        return similarity >= threshold, similarity

    def _update_centroid(self, new_embedding: np.ndarray, similarity: float):
        """Update centroid using windowed adaptation with enrollment anchor.

        Maintains a sliding window of recent high-confidence embeddings,
        computes their similarity-weighted mean, then blends 75% adapted + 25% enrollment.
        """
        with self._lock:
            if self._centroid is None:
                return

            # Dimension guard: reject embeddings that don't match centroid dimension
            if new_embedding.shape[0] != self._centroid.shape[0]:
                logger.error(
                    f"Centroid update rejected: embedding dim {new_embedding.shape[0]} "
                    f"!= centroid dim {self._centroid.shape[0]}"
                )
                return

            # Add to verified window
            self._verified_window.append((new_embedding.copy(), similarity))
            if len(self._verified_window) > self._max_window_size:
                self._verified_window = self._verified_window[-self._max_window_size:]

            # Compute similarity-weighted mean of window
            weights = np.array([s for _, s in self._verified_window])
            embeddings = np.array([e for e, _ in self._verified_window])
            weighted_mean = np.average(embeddings, axis=0, weights=weights)

            # Blend: 75% adapted + 25% enrollment centroid
            if self._enrollment_centroid is not None:
                blended = 0.75 * weighted_mean + 0.25 * self._enrollment_centroid
            else:
                blended = weighted_mean

            # Re-normalize
            norm = np.linalg.norm(blended)
            if norm > 0:
                blended = blended / norm

            # Final dimension check before persisting
            if blended.shape[0] != self.EXPECTED_EMBEDDING_DIM:
                logger.error(
                    f"Centroid update aborted: result dim {blended.shape[0]} "
                    f"!= expected {self.EXPECTED_EMBEDDING_DIM}"
                )
                return

            self._centroid = blended

        # Persist updated centroid
        if self.db:
            self.db.update_speaker_centroid(self._centroid.tobytes())

    def _handle_verification_failure(self):
        """Handle verification failure — rollback centroid after consecutive failures."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 5 and self._enrollment_centroid is not None:
            with self._lock:
                self._centroid = self._enrollment_centroid.copy()
                self._verified_window.clear()
            if self.db:
                self.db.update_speaker_centroid(self._centroid.tobytes())
            self._consecutive_failures = 0
            logger.info("Centroid rolled back to enrollment (5 consecutive failures)")

    def _apply_stale_bias(self):
        """If no verification in 24h, blend centroid 50/50 with enrollment."""
        if self._last_verification_ts is None or self._enrollment_centroid is None:
            return
        elapsed = time.time() - self._last_verification_ts
        if elapsed > 86400:  # 24 hours
            with self._lock:
                self._centroid = 0.5 * self._centroid + 0.5 * self._enrollment_centroid
                norm = np.linalg.norm(self._centroid)
                if norm > 0:
                    self._centroid = self._centroid / norm
            self._last_verification_ts = time.time()  # Don't re-apply every call
            logger.info("Applied stale bias — blended centroid with enrollment")

    def delete_profile(self):
        """Delete voice profile and reset to unfiltered mode."""
        with self._lock:
            self._centroid = None
            self._enrolled = False

        if self.db:
            self.db.delete_speaker_profile()

        logger.info("Voice profile deleted")

    def get_status(self) -> dict:
        """Get current speaker verification status."""
        status = {
            'enrolled': self._enrolled,
            'model_loaded': self.model is not None,
            'threshold': self.threshold,
        }
        if self.db:
            samples = self.db.get_enrollment_samples()
            status['enrollment_samples'] = len(samples) if samples else 0
            profile = self.db.get_speaker_profile()
            if profile:
                status['enrolled_at'] = profile.get('created_at')
                status['num_enrollment_samples'] = profile.get('num_enrollment_samples', 0)
        return status
