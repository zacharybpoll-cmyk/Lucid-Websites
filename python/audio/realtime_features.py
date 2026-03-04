"""
Real-time voice feature extraction for Live Voice Studio.
Lightweight DSP path: F0, jitter, HNR, ZCR — computable in <100ms per 500ms chunk.
No ML models. No speaker gate. No VAD. Deliberately simplified for fast feedback.
"""
import numpy as np
import librosa
import logging
from typing import Dict, Optional

logger = logging.getLogger('lucid.realtime')


class RealtimeFeatureExtractor:
    """
    Extracts a small set of fast-computable acoustic features from 500ms audio chunks.

    Only 3 features are exposed to the UI (per spec):
    - jitter: Vocal Steadiness proxy
    - hnr: Voice Clarity
    - f0_variance: Tone Stability (std of F0)

    Additional features computed internally for completeness but not sent to UI.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._last_features: Optional[Dict] = None

    def extract(self, audio_chunk: np.ndarray) -> Dict[str, float]:
        """
        Extract real-time features from a 500ms audio chunk.
        Returns dict with keys: jitter, hnr, f0_mean, f0_variance, zcr, rms_energy
        All values are floats in [0, 1] range (normalized for UI display).
        On error, returns last known values or zeros.
        """
        if len(audio_chunk) < self.sample_rate * 0.1:  # Need at least 100ms
            return self._last_features or self._zeros()

        try:
            audio = audio_chunk.astype(np.float32)

            features = {}

            # F0 (fundamental frequency) via pyin
            f0, voiced_flag, _ = librosa.pyin(
                audio,
                fmin=librosa.note_to_hz('C2'),
                fmax=librosa.note_to_hz('C7'),
                sr=self.sample_rate
            )
            f0_voiced = f0[~np.isnan(f0)] if f0 is not None else np.array([])

            if len(f0_voiced) > 2:
                features['f0_mean'] = float(np.mean(f0_voiced))
                features['f0_variance'] = float(np.std(f0_voiced))

                # Jitter: normalized pitch period variation
                periods = 1.0 / f0_voiced
                if len(periods) > 1:
                    jitter_abs = float(np.mean(np.abs(np.diff(periods))))
                    mean_period = float(np.mean(periods))
                    raw_jitter = jitter_abs / mean_period if mean_period > 0 else 0.0
                    # Normalize: typical jitter range 0-0.05, clip and invert for "steadiness"
                    features['jitter'] = float(np.clip(raw_jitter / 0.05, 0, 1))
                else:
                    features['jitter'] = 0.5

                # F0 variance normalized (typical std range 0-50Hz)
                features['f0_variance'] = float(np.clip(features['f0_variance'] / 50.0, 0, 1))
            else:
                features['f0_mean'] = 0.0
                features['f0_variance'] = 0.5
                features['jitter'] = 0.5

            # HNR (harmonic-to-noise ratio) via autocorrelation
            # Simplified: autocorrelation peak strength as proxy for harmonicity
            corr = np.correlate(audio, audio, mode='full')
            corr = corr[len(corr) // 2:]
            if len(corr) > 1 and corr[0] > 0:
                # Find peak in pitch range (65-500Hz → 32-246 samples at 16kHz)
                min_lag = int(self.sample_rate / 500)
                max_lag = int(self.sample_rate / 65)
                if max_lag < len(corr):
                    peak = float(np.max(corr[min_lag:max_lag]))
                    hnr_raw = peak / float(corr[0])
                    features['hnr'] = float(np.clip(hnr_raw, 0, 1))
                else:
                    features['hnr'] = 0.5
            else:
                features['hnr'] = 0.5

            # ZCR
            zcr = librosa.feature.zero_crossing_rate(audio)[0]
            features['zcr'] = float(np.clip(np.mean(zcr) / 0.3, 0, 1))

            # RMS energy
            rms = librosa.feature.rms(y=audio)[0]
            features['rms_energy'] = float(np.clip(np.mean(rms) / 0.1, 0, 1))

            # Build UI-facing output: invert jitter (higher = steadier) and f0_variance (higher variance = less stable)
            result = {
                'vocal_steadiness': float(1.0 - features['jitter']),   # Higher = steadier
                'voice_clarity': features['hnr'],
                'tone_stability': float(1.0 - features['f0_variance']), # Higher = more stable
                'f0_mean': features['f0_mean'],
                'rms_energy': features['rms_energy'],
                'raw_jitter': features['jitter'],
                'raw_hnr': features['hnr'],
            }

            self._last_features = result
            return result

        except Exception as e:
            logger.warning(f"Realtime feature extraction error: {e}")
            return self._last_features or self._zeros()

    def _zeros(self) -> Dict[str, float]:
        return {
            'vocal_steadiness': 0.5,
            'voice_clarity': 0.5,
            'tone_stability': 0.5,
            'f0_mean': 0.0,
            'rms_energy': 0.0,
            'raw_jitter': 0.5,
            'raw_hnr': 0.5,
        }
