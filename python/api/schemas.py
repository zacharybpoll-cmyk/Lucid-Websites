"""
Pydantic schemas for API responses
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

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

class TodayResponse(BaseModel):
    current_scores: Dict[str, Any]
    readings: List[Reading]
    summary: Optional[DailySummary] = None
    calibration_status: Dict[str, Any]

class StatusResponse(BaseModel):
    is_running: bool
    is_paused: bool
    meeting_active: bool
    buffered_speech_sec: float
    buffered_vad_confidence: Optional[float] = None
    calibration_status: Dict[str, Any]
    speaker_enrolled: Optional[bool] = None
    enrollment_required: Optional[bool] = None
    speaker_gate_stats: Optional[Dict[str, Any]] = None

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
