"""
Configuration constants for Attune
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    """Centralized application configuration."""

    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent)
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get('ATTUNE_DATA_DIR') or (Path(__file__).parent / "data")
    ))
    dam_dir: Path = field(default_factory=lambda: Path(__file__).parent / "dam")

    # Brand Colors
    brand_primary: str = "#EBE4DA"      # Warm off-white/beige (backgrounds)
    brand_secondary: str = "#5B5854"    # Warm gray (accents, borders)

    # Zone Colors (steel-gray palette, aligned with frontend CSS)
    zone_stressed: str = "#4B5563"      # Charcoal
    zone_tense: str = "#6B7280"         # Darker gray
    zone_steady: str = "#8C96A0"        # Medium gray
    zone_calm: str = "#7BA7C9"          # Light steel blue

    # Audio Settings
    sample_rate: int = 16000            # Hz (required by DAM model)
    channels: int = 1                   # Mono
    chunk_duration_ms: int = 32         # Silero VAD requires minimum 32ms chunks (512 samples at 16kHz)
    speech_threshold_sec: int = 30      # Soft trigger: start grace period at 30s of speech
    preferred_speech_sec: int = 60      # Hard trigger: optimal DAM reliability at 60s
    buffer_size_sec: int = 90           # Max buffer size before force-analysis
    grace_period_sec: int = 4           # After soft trigger, wait this long for more speech before analyzing

    # Temporal Smoothing
    ema_alpha: float = 0.4              # Exponential moving average alpha (0.4 = half-life ~1.3 readings)

    # Analysis Settings
    analysis_interval_sec: int = 5      # How often frontend polls for new data
    calibration_days: int = 3           # Days to collect baseline data

    # Score Thresholds (zone classification)
    stress_threshold_high: int = 70     # Above this = "Stressed"
    stress_threshold_med: int = 40      # Above this = "Tense"

    # Meeting Detection
    meeting_poll_interval_sec: int = 30 # How often to check for Zoom/Teams
    meeting_end_timeout_sec: int = 120  # Seconds of inactivity before auto-end meeting

    # FastAPI Settings
    api_host: str = "127.0.0.1"
    api_port: int = field(default_factory=lambda: int(os.environ.get('ATTUNE_API_PORT', '8765')))

    # Speaker Verification (ECAPA-TDNN)
    speaker_model_source: str = "speechbrain/spkrec-ecapa-voxceleb"
    speaker_verification_threshold: float = 0.28    # Cosine similarity threshold for accept/reject
    speaker_high_confidence: float = 0.75           # Above this, update centroid via EMA
    speaker_enrollment_required: bool = True        # Block analysis until voice profile is set up
    speaker_rms_minimum: float = 0.005              # Reject audio chunks below this RMS energy

    # Speaker Gate — segment-level verification (Phase 2)
    speaker_gate_segment_sec: float = 2.0           # Mini-buffer duration before verifying a segment
    speaker_gate_threshold: float = 0.28            # Verification threshold for segments

    # Speaker Gate — wall-clock timeout (prevents slow readings during sparse VAD)
    speaker_gate_max_wall_sec: float = 2.5          # Max wall-clock time before forcing verification
    speaker_gate_min_speech_sec: float = 0.5        # Minimum speech required for early verification

    # Speaker Gate — sandwich/continuity recovery
    speaker_gate_sandwich_threshold: float = 0.24   # Borderline segments above this can be recovered

    # Speaker Gate — momentum (adaptive threshold during sustained speech)
    speaker_gate_momentum_window: int = 5           # Consecutive verified segments to activate momentum
    speaker_gate_momentum_threshold: float = 0.24   # Lowered threshold while momentum is active
    speaker_gate_momentum_decay: int = 1            # Consecutive rejections to deactivate momentum
    speaker_gate_momentum_min_sim: float = 0.26     # Minimum similarity to use momentum threshold
    speaker_gate_absolute_floor: float = 0.22       # Below this similarity, always reject

    # Overlap Detection
    overlap_detection_enabled: bool = True          # Pitch-based multi-speaker overlap detection

    # PLDA Scoring (optional, disabled by default)
    plda_enabled: bool = False                      # Enable only when trained PLDA model exists

    # VAD Settings
    vad_speech_threshold: float = 0.40              # Silero VAD speech probability threshold

    @property
    def db_path(self) -> Path:
        return self.data_dir / "burnout.db"

    @property
    def plda_model_path(self) -> Path:
        return self.data_dir / "plda_model.pkl"


config = AppConfig()

# Ensure directories exist
config.data_dir.mkdir(parents=True, exist_ok=True)

# Backwards-compatible module-level access
BASE_DIR = config.base_dir
DATA_DIR = config.data_dir
DB_PATH = config.db_path
DAM_DIR = config.dam_dir

# Brand Colors
BRAND_PRIMARY = config.brand_primary
BRAND_SECONDARY = config.brand_secondary

# Zone Colors
ZONE_STRESSED = config.zone_stressed
ZONE_TENSE = config.zone_tense
ZONE_STEADY = config.zone_steady
ZONE_CALM = config.zone_calm

# Audio Settings
SAMPLE_RATE = config.sample_rate
CHANNELS = config.channels
CHUNK_DURATION_MS = config.chunk_duration_ms
SPEECH_THRESHOLD_SEC = config.speech_threshold_sec
PREFERRED_SPEECH_SEC = config.preferred_speech_sec
BUFFER_SIZE_SEC = config.buffer_size_sec
GRACE_PERIOD_SEC = config.grace_period_sec

# Temporal Smoothing
EMA_ALPHA = config.ema_alpha

# Analysis Settings
ANALYSIS_INTERVAL_SEC = config.analysis_interval_sec
CALIBRATION_DAYS = config.calibration_days

# Score Thresholds
STRESS_THRESHOLD_HIGH = config.stress_threshold_high
STRESS_THRESHOLD_MED = config.stress_threshold_med

# Meeting Detection
MEETING_POLL_INTERVAL_SEC = config.meeting_poll_interval_sec
MEETING_END_TIMEOUT_SEC = config.meeting_end_timeout_sec

# FastAPI Settings
API_HOST = config.api_host
API_PORT = config.api_port

# Speaker Verification
SPEAKER_MODEL_SOURCE = config.speaker_model_source
SPEAKER_VERIFICATION_THRESHOLD = config.speaker_verification_threshold
SPEAKER_HIGH_CONFIDENCE = config.speaker_high_confidence
SPEAKER_ENROLLMENT_REQUIRED = config.speaker_enrollment_required
SPEAKER_RMS_MINIMUM = config.speaker_rms_minimum

# Speaker Gate
SPEAKER_GATE_SEGMENT_SEC = config.speaker_gate_segment_sec
SPEAKER_GATE_THRESHOLD = config.speaker_gate_threshold
SPEAKER_GATE_MAX_WALL_SEC = config.speaker_gate_max_wall_sec
SPEAKER_GATE_MIN_SPEECH_SEC = config.speaker_gate_min_speech_sec
SPEAKER_GATE_SANDWICH_THRESHOLD = config.speaker_gate_sandwich_threshold
SPEAKER_GATE_MOMENTUM_WINDOW = config.speaker_gate_momentum_window
SPEAKER_GATE_MOMENTUM_THRESHOLD = config.speaker_gate_momentum_threshold
SPEAKER_GATE_MOMENTUM_DECAY = config.speaker_gate_momentum_decay
SPEAKER_GATE_MOMENTUM_MIN_SIM = config.speaker_gate_momentum_min_sim
SPEAKER_GATE_ABSOLUTE_FLOOR = config.speaker_gate_absolute_floor

# Overlap Detection
OVERLAP_DETECTION_ENABLED = config.overlap_detection_enabled

# PLDA Scoring
PLDA_MODEL_PATH = config.plda_model_path
PLDA_ENABLED = config.plda_enabled

# VAD Settings
VAD_SPEECH_THRESHOLD = config.vad_speech_threshold
