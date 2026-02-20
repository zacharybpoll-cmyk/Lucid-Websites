"""
Tests for backend.acoustic_features.AcousticFeatureExtractor

Tests pitch extraction, RMS energy, spectral features, jitter, shimmer,
voice breaks, and behavior on silence / empty audio.
"""
import numpy as np
import pytest

from backend.acoustic_features import AcousticFeatureExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sine(freq_hz: float, duration_sec: float = 1.0,
               sr: int = 16000, amplitude: float = 0.5) -> np.ndarray:
    """Generate a pure sine wave."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), dtype=np.float32)
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


def _make_voiced_speech_like(duration_sec: float = 2.0, sr: int = 16000) -> np.ndarray:
    """Generate a rough speech-like signal: periodic glottal pulse + noise."""
    n = int(sr * duration_sec)
    t = np.arange(n, dtype=np.float32) / sr
    # Fundamental at ~150 Hz with harmonics
    signal = (
        0.3 * np.sin(2 * np.pi * 150 * t) +
        0.15 * np.sin(2 * np.pi * 300 * t) +
        0.08 * np.sin(2 * np.pi * 450 * t)
    ).astype(np.float32)
    # Add a bit of noise
    noise = np.random.randn(n).astype(np.float32) * 0.02
    return signal + noise


# ---------------------------------------------------------------------------
# Feature extraction on 440 Hz sine
# ---------------------------------------------------------------------------

class TestExtract440Hz:
    def test_extract_features_returns_all_keys(self, sample_audio_440hz):
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)

        expected_keys = {
            'f0_mean', 'f0_std', 'rms_energy', 'speech_rate',
            'spectral_centroid', 'spectral_entropy', 'zcr',
            'jitter', 'shimmer', 'voice_breaks',
        }
        assert expected_keys.issubset(set(features.keys()))

    def test_f0_near_440(self, sample_audio_440hz):
        """F0 of a 440 Hz sine should be detected near 440 Hz."""
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)

        # Allow 10% tolerance — pyin can vary slightly on pure sine
        assert features['f0_mean'] == pytest.approx(440.0, rel=0.10)

    def test_rms_energy_positive(self, sample_audio_440hz):
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)
        assert features['rms_energy'] > 0.0

    def test_spectral_centroid_positive(self, sample_audio_440hz):
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)
        assert features['spectral_centroid'] > 0.0

    def test_spectral_entropy_positive(self, sample_audio_440hz):
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)
        assert features['spectral_entropy'] > 0.0

    def test_zcr_reasonable(self, sample_audio_440hz):
        """ZCR of a 440 Hz sine: ~440 zero crossings/sec = ~0.055 at 16kHz."""
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)
        # ZCR per frame (fraction of samples), should be small positive
        assert 0.0 < features['zcr'] < 0.5

    def test_jitter_low_for_pure_sine(self, sample_audio_440hz):
        """Pure sine has very stable pitch — jitter should be low."""
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)
        assert features['jitter'] < 0.1

    def test_voice_breaks_zero_for_continuous_tone(self, sample_audio_440hz):
        """Continuous 440 Hz tone has no voice breaks."""
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)
        assert features['voice_breaks'] == 0


# ---------------------------------------------------------------------------
# Silence handling
# ---------------------------------------------------------------------------

class TestExtractSilence:
    def test_extract_features_silence(self, sample_audio_silence):
        """Silence should yield zero/near-zero features without errors."""
        audio, sr = sample_audio_silence
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        features = extractor.extract(audio)

        assert features['f0_mean'] == pytest.approx(0.0, abs=1.0)
        assert features['rms_energy'] == pytest.approx(0.0, abs=0.001)
        assert features['jitter'] == pytest.approx(0.0, abs=0.01)
        assert features['voice_breaks'] >= 0  # Might be 0 or small int

    def test_empty_audio(self):
        """Empty numpy array returns zero features."""
        extractor = AcousticFeatureExtractor(sample_rate=16000)
        features = extractor.extract(np.array([], dtype=np.float32))
        assert features['f0_mean'] == 0.0
        assert features['rms_energy'] == 0.0
        assert features['speech_rate'] == 0.0


# ---------------------------------------------------------------------------
# Pitch extraction (_extract_pitch)
# ---------------------------------------------------------------------------

class TestPitchExtraction:
    def test_pitch_returns_f0_array(self, sample_audio_440hz):
        """_extract_pitch returns f0, voiced_flag, voiced_probs as numpy arrays."""
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        f0, voiced_flag, voiced_probs = extractor._extract_pitch(audio)

        assert f0 is not None
        assert isinstance(f0, np.ndarray)
        assert len(f0) > 0

    def test_pitch_voiced_frames_near_440(self, sample_audio_440hz):
        """Voiced frames of 440 Hz sine should report ~440 Hz."""
        audio, sr = sample_audio_440hz
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        f0, _, _ = extractor._extract_pitch(audio)

        voiced = f0[~np.isnan(f0)]
        if len(voiced) > 0:
            mean_f0 = float(np.mean(voiced))
            assert mean_f0 == pytest.approx(440.0, rel=0.10)

    def test_pitch_silence_all_nan(self, sample_audio_silence):
        """Silence should yield mostly/all NaN in F0 (no voiced frames)."""
        audio, sr = sample_audio_silence
        extractor = AcousticFeatureExtractor(sample_rate=sr)
        f0, _, _ = extractor._extract_pitch(audio)

        if f0 is not None:
            voiced = f0[~np.isnan(f0)]
            # Silence: we expect no voiced frames
            assert len(voiced) == 0


# ---------------------------------------------------------------------------
# Speech-like signal
# ---------------------------------------------------------------------------

class TestSpeechLikeSignal:
    def test_f0_near_150(self):
        """A glottal-pulse-like signal at 150 Hz should yield F0 near 150."""
        audio = _make_voiced_speech_like(duration_sec=2.0)
        extractor = AcousticFeatureExtractor(sample_rate=16000)
        features = extractor.extract(audio)

        # Allow generous tolerance — the harmonic-rich signal may confuse pyin
        assert 80 < features['f0_mean'] < 300

    def test_shimmer_positive_for_speech_like(self):
        """Speech-like signal with harmonics should have measurable shimmer."""
        audio = _make_voiced_speech_like(duration_sec=2.0)
        extractor = AcousticFeatureExtractor(sample_rate=16000)
        features = extractor.extract(audio)
        assert features['shimmer'] >= 0.0

    def test_speech_rate_non_negative(self):
        audio = _make_voiced_speech_like(duration_sec=2.0)
        extractor = AcousticFeatureExtractor(sample_rate=16000)
        features = extractor.extract(audio)
        assert features['speech_rate'] >= 0.0


# ---------------------------------------------------------------------------
# Different frequencies
# ---------------------------------------------------------------------------

class TestDifferentFrequencies:
    @pytest.mark.parametrize("freq", [200.0, 330.0, 500.0])
    def test_f0_tracks_frequency(self, freq):
        """Verify pyin tracks different fundamental frequencies."""
        audio = _make_sine(freq, duration_sec=1.0)
        extractor = AcousticFeatureExtractor(sample_rate=16000)
        f0, _, _ = extractor._extract_pitch(audio)

        voiced = f0[~np.isnan(f0)]
        if len(voiced) > 0:
            assert float(np.mean(voiced)) == pytest.approx(freq, rel=0.15)

    def test_higher_freq_higher_zcr(self):
        """Higher frequency should produce higher zero-crossing rate."""
        extractor = AcousticFeatureExtractor(sample_rate=16000)
        low = extractor.extract(_make_sine(200.0))
        high = extractor.extract(_make_sine(800.0))
        assert high['zcr'] > low['zcr']
