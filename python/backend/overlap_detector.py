"""
Overlap Detector — pitch-based multi-speaker detection.

Uses librosa's pyin pitch tracker to detect bimodal pitch distributions,
which indicate two speakers talking simultaneously. Segments with detected
overlap are rejected before ECAPA verification (saves compute).
"""
import logging
import numpy as np

logger = logging.getLogger('attune.overlap')


class OverlapDetector:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._available = False
        try:
            import librosa
            self._librosa = librosa
            self._available = True
        except ImportError:
            logger.warning("librosa not available — overlap detection disabled")

    def detect_overlap(self, audio: np.ndarray) -> bool:
        """Detect if audio contains overlapping speakers via bimodal pitch.

        Args:
            audio: float32 mono audio at self.sample_rate

        Returns:
            True if overlap detected, False otherwise (including on any error)
        """
        if not self._available:
            return False

        try:
            # Extract pitch using pyin
            f0, voiced_flag, _ = self._librosa.pyin(
                audio.astype(np.float32),
                fmin=self._librosa.note_to_hz('C2'),  # ~65 Hz
                fmax=self._librosa.note_to_hz('C6'),  # ~1047 Hz
                sr=self.sample_rate,
            )

            # Filter to voiced frames only
            voiced_f0 = f0[voiced_flag]
            if len(voiced_f0) < 10:
                return False  # Not enough voiced frames to analyze

            # Check for bimodal distribution using two-cluster analysis
            median_f0 = np.median(voiced_f0)
            low_cluster = voiced_f0[voiced_f0 < median_f0]
            high_cluster = voiced_f0[voiced_f0 >= median_f0]

            if len(low_cluster) < 3 or len(high_cluster) < 3:
                return False

            low_mean = np.mean(low_cluster)
            high_mean = np.mean(high_cluster)

            # Ratio of cluster centers — if >= 1.5, likely two different speakers
            if low_mean > 0:
                ratio = high_mean / low_mean
                if ratio >= 1.5:
                    logger.debug(f"Overlap detected: pitch ratio={ratio:.2f} "
                                 f"(low={low_mean:.0f}Hz, high={high_mean:.0f}Hz)")
                    return True

            return False

        except Exception as e:
            logger.debug(f"Overlap detection error (non-fatal): {e}")
            return False
