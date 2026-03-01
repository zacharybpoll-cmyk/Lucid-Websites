"""
Pydantic schemas for API responses
"""
from pydantic import BaseModel, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime


class ReadingInsert(BaseModel):
    """Validation model for inserting a new reading into the database.
    All fields optional except timestamp (auto-generated if missing).
    Validates ranges before data reaches SQLite."""
    timestamp: Optional[str] = None
    depression_raw: Optional[float] = None
    anxiety_raw: Optional[float] = None
    depression_quantized: Optional[int] = None
    anxiety_quantized: Optional[int] = None
    depression_mapped: Optional[float] = None
    anxiety_mapped: Optional[float] = None
    f0_mean: Optional[float] = None
    f0_std: Optional[float] = None
    speech_rate: Optional[float] = None
    rms_energy: Optional[float] = None
    spectral_centroid: Optional[float] = None
    spectral_entropy: Optional[float] = None
    zcr: Optional[float] = None
    jitter: Optional[float] = None
    shimmer: Optional[float] = None
    voice_breaks: Optional[int] = None
    stress_score: Optional[float] = None
    mood_score: Optional[float] = None
    energy_score: Optional[float] = None
    calm_score: Optional[float] = None
    stress_score_raw: Optional[float] = None
    mood_score_raw: Optional[float] = None
    energy_score_raw: Optional[float] = None
    calm_score_raw: Optional[float] = None
    zone: Optional[str] = None
    speech_duration_sec: Optional[float] = None
    meeting_detected: Optional[int] = 0
    vad_confidence: Optional[float] = None
    low_confidence: Optional[int] = 0
    depression_ci_lower: Optional[float] = None
    depression_ci_upper: Optional[float] = None
    anxiety_ci_lower: Optional[float] = None
    anxiety_ci_upper: Optional[float] = None
    uncertainty_flag: Optional[str] = None
    score_inconsistency: Optional[int] = 0
    speaker_verified: Optional[int] = -1
    speaker_similarity: Optional[float] = None
    wellbeing_score: Optional[float] = None
    wellbeing_score_raw: Optional[float] = None
    depression_risk_score: Optional[float] = None
    depression_risk_score_raw: Optional[float] = None
    activation_score: Optional[float] = None
    activation_score_raw: Optional[float] = None
    anxiety_risk_score: Optional[float] = None
    anxiety_risk_score_raw: Optional[float] = None
    emotional_stability_score: Optional[float] = None
    emotional_stability_score_raw: Optional[float] = None
    alpha_ratio: Optional[float] = None
    mfcc3: Optional[float] = None
    pitch_range: Optional[float] = None
    rms_sd: Optional[float] = None
    phonation_ratio: Optional[float] = None
    h1_h2: Optional[float] = None
    hnr: Optional[float] = None
    voice_tremor_index: Optional[float] = None
    pause_mean: Optional[float] = None
    pause_sd: Optional[float] = None
    pause_rate: Optional[float] = None

    @field_validator('stress_score', 'mood_score', 'energy_score', 'calm_score',
                     'stress_score_raw', 'mood_score_raw', 'energy_score_raw', 'calm_score_raw',
                     'wellbeing_score', 'wellbeing_score_raw',
                     'activation_score', 'activation_score_raw',
                     'depression_risk_score', 'depression_risk_score_raw',
                     'anxiety_risk_score', 'anxiety_risk_score_raw',
                     'emotional_stability_score', 'emotional_stability_score_raw',
                     mode='before')
    @classmethod
    def clamp_scores(cls, v):
        """Clamp score fields to 0-100 range"""
        if v is None:
            return v
        return max(0.0, min(100.0, float(v)))

    @field_validator('f0_mean', mode='before')
    @classmethod
    def validate_f0(cls, v):
        """Validate fundamental frequency range (0-1000 Hz)"""
        if v is None:
            return v
        v = float(v)
        if v < 0 or v > 1000:
            raise ValueError(f'f0_mean must be between 0 and 1000 Hz, got {v}')
        return v

    @field_validator('zone', mode='before')
    @classmethod
    def validate_zone(cls, v):
        """Validate zone is one of the known values"""
        if v is None:
            return v
        valid_zones = {'stressed', 'tense', 'steady', 'calm'}
        if v not in valid_zones:
            raise ValueError(f'zone must be one of {valid_zones}, got {v!r}')
        return v

    @field_validator('speech_duration_sec', mode='before')
    @classmethod
    def validate_speech_duration(cls, v):
        """Speech duration must be non-negative"""
        if v is None:
            return v
        v = float(v)
        if v < 0:
            raise ValueError(f'speech_duration_sec must be >= 0, got {v}')
        return v


class Reading(BaseModel):
    id: int
    timestamp: str
    depression_raw: Optional[float] = None
    anxiety_raw: Optional[float] = None
    depression_quantized: Optional[int] = None
    anxiety_quantized: Optional[int] = None
    f0_mean: Optional[float] = None
    f0_std: Optional[float] = None
    speech_rate: Optional[float] = None
    rms_energy: Optional[float] = None
    spectral_centroid: Optional[float] = None
    spectral_entropy: Optional[float] = None
    zcr: Optional[float] = None
    jitter: Optional[float] = None
    shimmer: Optional[float] = None
    voice_breaks: Optional[int] = None
    stress_score: Optional[float] = None
    mood_score: Optional[float] = None
    energy_score: Optional[float] = None
    calm_score: Optional[float] = None
    stress_score_raw: Optional[float] = None
    mood_score_raw: Optional[float] = None
    energy_score_raw: Optional[float] = None
    calm_score_raw: Optional[float] = None
    wellbeing_score: Optional[float] = None
    wellbeing_score_raw: Optional[float] = None
    activation_score: Optional[float] = None
    activation_score_raw: Optional[float] = None
    depression_risk_score: Optional[float] = None
    depression_risk_score_raw: Optional[float] = None
    anxiety_risk_score: Optional[float] = None
    anxiety_risk_score_raw: Optional[float] = None
    emotional_stability_score: Optional[float] = None
    emotional_stability_score_raw: Optional[float] = None
    alpha_ratio: Optional[float] = None
    mfcc3: Optional[float] = None
    pitch_range: Optional[float] = None
    rms_sd: Optional[float] = None
    phonation_ratio: Optional[float] = None
    h1_h2: Optional[float] = None
    hnr: Optional[float] = None
    voice_tremor_index: Optional[float] = None
    pause_mean: Optional[float] = None
    pause_sd: Optional[float] = None
    pause_rate: Optional[float] = None
    zone: Optional[str] = None
    speech_duration_sec: Optional[float] = None
    depression_mapped: Optional[float] = None
    anxiety_mapped: Optional[float] = None
    depression_ci_lower: Optional[float] = None
    depression_ci_upper: Optional[float] = None
    anxiety_ci_lower: Optional[float] = None
    anxiety_ci_upper: Optional[float] = None
    uncertainty_flag: Optional[str] = None
    score_inconsistency: Optional[int] = None
    vad_confidence: Optional[float] = None
    low_confidence: Optional[int] = None
    meeting_detected: Optional[int] = None

    @field_validator('stress_score', 'mood_score', 'energy_score', 'calm_score',
                     'stress_score_raw', 'mood_score_raw', 'energy_score_raw', 'calm_score_raw',
                     'wellbeing_score', 'wellbeing_score_raw',
                     'activation_score', 'activation_score_raw',
                     'depression_risk_score', 'depression_risk_score_raw',
                     'anxiety_risk_score', 'anxiety_risk_score_raw',
                     'emotional_stability_score', 'emotional_stability_score_raw',
                     mode='before')
    @classmethod
    def clamp_scores(cls, v):
        """Clamp score fields to 0-100 range"""
        if v is None:
            return v
        return max(0.0, min(100.0, float(v)))

    @field_validator('f0_mean', mode='before')
    @classmethod
    def validate_f0(cls, v):
        """Validate fundamental frequency range (0-1000 Hz)"""
        if v is None:
            return v
        v = float(v)
        if v < 0 or v > 1000:
            raise ValueError(f'f0_mean must be between 0 and 1000 Hz, got {v}')
        return v

class DailySummary(BaseModel):
    date: str
    avg_depression: Optional[float] = None
    avg_anxiety: Optional[float] = None
    avg_stress: Optional[float] = None
    avg_mood: Optional[float] = None
    avg_energy: Optional[float] = None
    avg_calm: Optional[float] = None
    peak_stress: Optional[float] = None
    time_in_stressed_min: Optional[float] = None
    time_in_tense_min: Optional[float] = None
    time_in_steady_min: Optional[float] = None
    time_in_calm_min: Optional[float] = None
    total_speech_min: Optional[float] = None
    total_meetings: Optional[int] = None
    burnout_risk: Optional[float] = None
    resilience_score: Optional[float] = None
    avg_wellbeing: Optional[float] = None
    avg_activation: Optional[float] = None
    avg_depression_risk: Optional[float] = None
    avg_anxiety_risk: Optional[float] = None
    avg_emotional_stability: Optional[float] = None

class TodayResponse(BaseModel):
    current_scores: Dict[str, Any]
    readings: List[Reading]
    summary: Optional[DailySummary] = None
    calibration_status: Dict[str, Any]
    total_readings: int = 0

class StatusResponse(BaseModel):
    is_running: bool
    is_paused: bool
    meeting_active: bool
    is_analyzing: bool = False
    last_analysis_error: Optional[str] = None
    analysis_success_count: int = 0
    buffered_speech_sec: float
    buffered_vad_confidence: Optional[float] = None
    calibration_status: Dict[str, Any]
    speaker_enrolled: Optional[bool] = None
    enrollment_required: Optional[bool] = None
    speaker_gate_stats: Optional[Dict[str, Any]] = None
    mic_disconnected: bool = False

class TagRequest(BaseModel):
    timestamp: str
    label: str
    notes: Optional[str] = ""

class TagResponse(BaseModel):
    id: int
    timestamp: str
    label: str
    notes: Optional[str] = None

class MeetingToggleRequest(BaseModel):
    active: bool

class EnrollSampleRequest(BaseModel):
    mood_label: str  # 'neutral', 'animated', 'calm'

class SpeakerStatusResponse(BaseModel):
    enrolled: bool
    model_loaded: bool
    threshold: float
    enrollment_samples: int = 0
    enrolled_at: Optional[str] = None
    num_enrollment_samples: int = 0


# --- Models extracted from routes.py inline definitions ---

class ReviveRequest(BaseModel):
    date: str

class IntentionRequest(BaseModel):
    intention: str

class LayoutRequest(BaseModel):
    cards: list

class FirstLightTaskRequest(BaseModel):
    task: str

class NotifPrefRequest(BaseModel):
    key: str
    value: str

class WebhookRequest(BaseModel):
    url: str
    trigger_type: str  # 'reading', 'zone_change'
    condition_field: Optional[str] = None
    condition_op: Optional[str] = None  # '>', '<', '>=', '<=', '=='
    condition_value: Optional[float] = None

class OnboardingStatusRequest(BaseModel):
    completed: bool
