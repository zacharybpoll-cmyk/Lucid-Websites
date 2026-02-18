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
import numpy as np
import torch
import torchaudio
import huggingface_hub
import threading
from typing import Tuple, Optional, List
from pathlib import Path
import app_config as config

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
        self._enrolled = False
        self.threshold = config.SPEAKER_VERIFICATION_THRESHOLD

    def load_model(self):
        """Load ECAPA-TDNN model from SpeechBrain. Call from background thread."""
        from speechbrain.inference.speaker import EncoderClassifier

        cache_dir = config.DATA_DIR / "speaker_model"
        cache_dir.mkdir(exist_ok=True)

        # Create placeholder custom.py (this model has no custom modules, but
        # SpeechBrain's from_hparams tries to fetch it and fails on 404)
        custom_py = cache_dir / "custom.py"
        if not custom_py.exists():
            custom_py.write_text("# Placeholder — this model has no custom modules\n")

        print("[SpeakerVerifier] Loading ECAPA-TDNN model...")
        self.model = EncoderClassifier.from_hparams(
            source=config.SPEAKER_MODEL_SOURCE,
            savedir=str(cache_dir),
            run_opts={"device": "cpu"},
        )
        print("[SpeakerVerifier] ECAPA-TDNN model loaded")

        # Load stored voiceprint if exists
        self._load_profile()

    def _load_profile(self):
        """Load voiceprint from database if enrolled."""
        if self.db is None:
            return
        profile = self.db.get_speaker_profile()
        if profile and profile.get('embedding') is not None:
            self._centroid = np.frombuffer(profile['embedding'], dtype=np.float32).copy()
            self._enrolled = True
            print(f"[SpeakerVerifier] Loaded voiceprint ({self._centroid.shape[0]}-dim)")
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

    def enroll_sample(self, audio: np.ndarray, mood_label: str) -> np.ndarray:
        """Process a single enrollment sample.

        Args:
            audio: raw audio (float32, 16kHz)
            mood_label: 'neutral', 'animated', or 'calm'

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

        with self._lock:
            self._centroid = centroid
            self._enrolled = True

        # Save profile to DB
        self.db.save_speaker_profile(
            embedding=centroid.tobytes(),
            embedding_dim=len(centroid),
            num_samples=len(embeddings),
            threshold=self.threshold,
        )

        print(f"[SpeakerVerifier] Enrollment complete — {len(embeddings)} samples → centroid")
        return centroid

    def verify(self, audio: np.ndarray) -> Tuple[bool, float]:
        """Verify if audio belongs to the enrolled speaker.

        Args:
            audio: speech segment (float32, 16kHz)

        Returns:
            (is_verified, similarity_score)
        """
        if not self._enrolled or self._centroid is None:
            return True, 1.0  # No profile → pass through

        embedding = self.get_embedding(audio)

        with self._lock:
            similarity = float(np.dot(embedding, self._centroid))

        is_verified = similarity >= self.threshold

        # Adaptive centroid update for high-confidence matches
        if is_verified and similarity >= config.SPEAKER_HIGH_CONFIDENCE:
            self._update_centroid(embedding, alpha=config.SPEAKER_ADAPTIVE_ALPHA)

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
            threshold = config.SPEAKER_GATE_THRESHOLD

        embedding = self.get_embedding(audio)

        with self._lock:
            similarity = float(np.dot(embedding, self._centroid))

        return similarity >= threshold, similarity

    def _update_centroid(self, new_embedding: np.ndarray, alpha: float = 0.02):
        """Update centroid via EMA for high-confidence verifications."""
        with self._lock:
            if self._centroid is None:
                return
            self._centroid = (1 - alpha) * self._centroid + alpha * new_embedding
            # Re-normalize
            norm = np.linalg.norm(self._centroid)
            if norm > 0:
                self._centroid = self._centroid / norm

        # Persist updated centroid
        if self.db:
            self.db.update_speaker_centroid(self._centroid.tobytes())

    def delete_profile(self):
        """Delete voice profile and reset to unfiltered mode."""
        with self._lock:
            self._centroid = None
            self._enrolled = False

        if self.db:
            self.db.delete_speaker_profile()

        print("[SpeakerVerifier] Voice profile deleted")

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
