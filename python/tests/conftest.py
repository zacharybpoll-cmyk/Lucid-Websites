"""Pytest fixtures for Attune test suite."""
import os
import sys
import tempfile
import numpy as np
import pytest

# Add python/ to path so we can import backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set data dir to temp for tests (must be set BEFORE importing app_config)
os.environ['ATTUNE_DATA_DIR'] = tempfile.mkdtemp()


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    from backend.database import Database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    db = Database(db_path=db_path)
    yield db
    db.close()
    os.unlink(db_path)


@pytest.fixture
def sample_audio_440hz():
    """Generate a 1-second 440Hz sine wave at 16kHz."""
    sr = 16000
    t = np.linspace(0, 1, sr, dtype=np.float32)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t)
    return audio, sr


@pytest.fixture
def sample_audio_silence():
    """Generate 1 second of silence at 16kHz."""
    return np.zeros(16000, dtype=np.float32), 16000


@pytest.fixture
def sample_reading():
    """Return a realistic reading dict for database insertion."""
    from datetime import datetime
    return {
        'timestamp': datetime.now().isoformat(),
        'depression_raw': 5.2,
        'anxiety_raw': 3.8,
        'depression_quantized': 5,
        'anxiety_quantized': 4,
        'depression_mapped': 8.1,
        'anxiety_mapped': 5.4,
        'f0_mean': 180.5,
        'f0_std': 25.3,
        'speech_rate': 3.5,
        'rms_energy': 0.045,
        'spectral_centroid': 1500.0,
        'spectral_entropy': 4.2,
        'zcr': 0.08,
        'jitter': 0.015,
        'shimmer': 0.06,
        'voice_breaks': 1,
        'stress_score': 45.0,
        'mood_score': 65.0,
        'energy_score': 55.0,
        'calm_score': 60.0,
        'stress_score_raw': 42.0,
        'mood_score_raw': 68.0,
        'energy_score_raw': 52.0,
        'calm_score_raw': 58.0,
        'zone': 'steady',
        'speech_duration_sec': 45.0,
        'meeting_detected': 0,
        'vad_confidence': 0.85,
        'low_confidence': 0,
        'depression_ci_lower': 3.0,
        'depression_ci_upper': 7.5,
        'anxiety_ci_lower': 2.0,
        'anxiety_ci_upper': 5.5,
        'uncertainty_flag': None,
        'score_inconsistency': 0,
        'speaker_verified': 1,
        'speaker_similarity': 0.72,
    }
