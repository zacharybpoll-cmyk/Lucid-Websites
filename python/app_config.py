"""
Configuration constants for Attune
"""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
# Allow Electron to override data directory via environment variable
_data_override = os.environ.get('ATTUNE_DATA_DIR')
DATA_DIR = Path(_data_override) if _data_override else BASE_DIR / "data"
DB_PATH = DATA_DIR / "burnout.db"
DAM_DIR = BASE_DIR / "dam"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Brand Colors
BRAND_PRIMARY = "#EBE4DA"      # Warm off-white/beige (backgrounds)
BRAND_SECONDARY = "#5B5854"    # Warm gray (accents, borders)
BRAND_TERTIARY = "#000000"     # Black (headings, primary text)
BRAND_FONT = "Times New Roman"

# Zone Colors (non-brand, for timeline visualization)
ZONE_STRESSED = "#C44E52"      # Muted red
ZONE_TENSE = "#DD8452"         # Warm amber
ZONE_STEADY = "#5B5854"        # Warm gray (reuses brand secondary)
ZONE_CALM = "#5B8DB8"          # Medical steel blue

# Audio Settings
SAMPLE_RATE = 16000            # Hz (required by DAM model)
CHANNELS = 1                   # Mono
CHUNK_DURATION_MS = 32         # Silero VAD requires minimum 32ms chunks (512 samples at 16kHz)
SPEECH_THRESHOLD_SEC = 30      # Soft trigger: start grace period at 30s of speech
PREFERRED_SPEECH_SEC = 60      # Hard trigger: optimal DAM reliability at 60s
BUFFER_SIZE_SEC = 90           # Max buffer size before force-analysis
GRACE_PERIOD_SEC = 15          # After soft trigger, wait this long for more speech before analyzing

# Temporal Smoothing
EMA_ALPHA = 0.4                # Exponential moving average alpha (0.4 = half-life ~1.3 readings)

# Analysis Settings
ANALYSIS_INTERVAL_SEC = 5      # How often frontend polls for new data
CALIBRATION_DAYS = 3           # Days to collect baseline data
BURNOUT_WINDOW_DAYS = 14       # Rolling window for burnout risk
CUMULATIVE_WINDOW_DAYS = 30    # Rolling window for cumulative stress

# Score Thresholds (zone classification)
STRESS_THRESHOLD_HIGH = 70     # Above this = "Stressed"
STRESS_THRESHOLD_MED = 40      # Above this = "Tense"
ANXIETY_THRESHOLD_HIGH = 10    # Raw DAM anxiety score for "Stressed"
ANXIETY_THRESHOLD_MED = 5      # Raw DAM anxiety score for "Tense"

# Meeting Detection
MEETING_POLL_INTERVAL_SEC = 30 # How often to check for Zoom/Teams
MEETING_END_TIMEOUT_SEC = 120  # Seconds of inactivity before auto-end meeting

# FastAPI Settings
API_HOST = "127.0.0.1"
API_PORT = 8765

# Work Hours (default, user can configure later)
WORK_START_HOUR = 9            # 9am
WORK_END_HOUR = 17             # 5pm

# Speaker Verification (ECAPA-TDNN)
SPEAKER_MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
SPEAKER_VERIFICATION_THRESHOLD = 0.28   # Cosine similarity threshold for accept/reject
SPEAKER_HIGH_CONFIDENCE = 0.75          # Above this, update centroid via EMA
SPEAKER_ADAPTIVE_ALPHA = 0.02           # EMA alpha for centroid drift
SPEAKER_ENROLLMENT_DURATION_SEC = 10    # Duration per enrollment sample
SPEAKER_ENROLLMENT_SAMPLES = 5          # Number of enrollment samples
SPEAKER_ENROLLMENT_REQUIRED = True      # Block analysis until voice profile is set up
SPEAKER_RMS_MINIMUM = 0.005             # Reject audio chunks below this RMS energy (distant speakers/TV)

# Speaker Gate — segment-level verification (Phase 2)
SPEAKER_GATE_SEGMENT_SEC = 1.2          # Mini-buffer duration before verifying a segment
SPEAKER_GATE_THRESHOLD = 0.28           # Verification threshold for segments (matches buffer-level)

# Speaker Gate — sandwich/continuity recovery
SPEAKER_GATE_SANDWICH_THRESHOLD = 0.24  # Borderline segments above this can be recovered if sandwiched

# Speaker Gate — momentum (adaptive threshold during sustained speech)
SPEAKER_GATE_MOMENTUM_WINDOW = 3        # Consecutive verified segments to activate momentum
SPEAKER_GATE_MOMENTUM_THRESHOLD = 0.24  # Lowered threshold while momentum is active
SPEAKER_GATE_MOMENTUM_DECAY = 2         # Consecutive rejections to deactivate momentum

# VAD Settings
VAD_SPEECH_THRESHOLD = 0.40             # Silero VAD speech probability threshold (default was 0.5)
