"""Engagement endpoints: self-assessment, voice season, notification timing."""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request

from api import dependencies as deps
from api.schemas import SelfAssessmentRequest, SelfAssessmentResponse
from backend.engagement import EngagementTracker

router = APIRouter()


# ============ Self-Assessment ============

@router.post("/api/self-assessment", response_model=SelfAssessmentResponse)
async def submit_self_assessment(request: SelfAssessmentRequest):
    """Submit a self-assessment of current zone (ground truth for calibration)."""
    if deps.db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    valid_zones = {'calm', 'steady', 'tense', 'stressed'}
    if request.zone not in valid_zones:
        raise HTTPException(status_code=400, detail=f"Zone must be one of: {valid_zones}")

    reading_id = request.reading_id
    if reading_id is None:
        reading_id = deps.db.get_nearest_reading_id()

    assessment_id = deps.db.insert_self_assessment(request.zone, reading_id)

    return {
        'id': assessment_id,
        'timestamp': datetime.now().isoformat(),
        'zone': request.zone,
        'reading_id': reading_id,
    }


@router.get("/api/self-assessment/status")
async def self_assessment_status():
    """Check if a self-assessment prompt should be shown."""
    if deps.db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    last_time = deps.db.get_last_self_assessment_time()
    should_prompt = True

    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            should_prompt = hours_since >= 30
        except (ValueError, TypeError):
            should_prompt = True

    nearest_reading_id = deps.db.get_nearest_reading_id()

    return {
        'should_prompt': should_prompt,
        'last_assessment': last_time,
        'nearest_reading_id': nearest_reading_id,
    }


@router.get("/api/self-assessments")
async def get_self_assessments():
    """Get recent self-assessments for review/calibration."""
    if deps.db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return deps.db.get_self_assessments(limit=100)


# ============ Voice Season ============

@router.get("/api/voice-season")
async def get_voice_season():
    """Get current voice season progress."""
    tracker = EngagementTracker(deps.db)
    return tracker.compute_voice_season()


# ============ Adaptive Notification Timing ============

@router.post("/api/notifications/open")
async def record_notification_open():
    """Record that a notification was opened."""
    deps.db.record_notification_open()
    return {'success': True}


@router.get("/api/notifications/timing")
async def get_notification_timing():
    """Get adaptive notification timing data."""
    nm = deps.notification_manager
    if not nm:
        return {'has_data': False}
    peak = nm.get_peak_window()
    adaptive_enabled = deps.db.get_notification_pref('adaptive_timing', 'false').lower() == 'true'
    return {**peak, 'adaptive_enabled': adaptive_enabled}


@router.put("/api/notifications/timing/enabled")
async def set_adaptive_timing(request: Request):
    """Enable/disable adaptive notification timing."""
    body = await request.json()
    enabled = body.get('enabled', False)
    deps.db.set_notification_pref('adaptive_timing', 'true' if enabled else 'false')
    return {'success': True, 'adaptive_enabled': enabled}
