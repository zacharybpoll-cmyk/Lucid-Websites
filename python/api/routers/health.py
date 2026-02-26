"""
Health, status, onboarding, pause/resume, and First Light quest endpoints.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from datetime import date, timedelta

from api import dependencies as deps
from api.schemas import StatusResponse, OnboardingStatusRequest, FirstLightTaskRequest

router = APIRouter()


@router.get("/api/health")
async def health():
    """Health check with model readiness status.
    ERR-002: Returns 503 when not ready so callers can distinguish loading from ready."""
    if deps.orchestrator is None:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "status": "initializing..."},
            headers={"Retry-After": "5"},
        )

    models_loaded = deps.orchestrator.models_ready.is_set()

    # Speaker enrollment status (included in base health for frontend pre-checks)
    speaker_enrolled = False
    enrollment_required = True
    if deps.orchestrator.speaker_verifier:
        sv_status = deps.orchestrator.speaker_verifier.get_status()
        speaker_enrolled = sv_status.get('enrolled', False)
    from app_config import config as cfg
    enrollment_required = cfg.speaker_enrollment_required

    if models_loaded:
        return {"ready": True, "status": "ready",
                "speaker_enrolled": speaker_enrolled,
                "enrollment_required": enrollment_required}
    else:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "status": "loading models...",
                     "speaker_enrolled": speaker_enrolled,
                     "enrollment_required": enrollment_required},
            headers={"Retry-After": "5"},
        )


@router.get("/api/health/ready")
async def health_ready():
    """Pre-flight check: verifies DB + models + speaker enrollment status."""
    checks = {
        'database': deps.db is not None and deps.db.health_check(),
        'orchestrator': deps.orchestrator is not None,
        'models_loaded': (deps.orchestrator is not None and
                         deps.orchestrator.models_ready.is_set()),
        'insight_engine': deps.insight_engine is not None,
    }

    # Speaker enrollment status
    speaker_enrolled = False
    if deps.orchestrator and deps.orchestrator.speaker_verifier:
        status = deps.orchestrator.speaker_verifier.get_status()
        speaker_enrolled = status.get('enrolled', False)
    checks['speaker_enrolled'] = speaker_enrolled

    all_ready = all(v for k, v in checks.items() if k != 'speaker_enrolled')

    if not all_ready:
        return JSONResponse(
            status_code=503,
            content={'ready': False, 'checks': checks},
            headers={"Retry-After": "5"},
        )

    return {'ready': True, 'checks': checks}


@router.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Get current system status"""
    if deps.orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    return deps.orchestrator.get_status()


@router.post("/api/pause")
async def pause_analysis():
    """Pause analysis"""
    if deps.orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    deps.orchestrator.pause()
    return {"status": "ok", "is_paused": True}


@router.post("/api/resume")
async def resume_analysis():
    """Resume analysis"""
    if deps.orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    deps.orchestrator.resume()
    return {"status": "ok", "is_paused": False}


@router.get("/api/onboarding-status")
async def get_onboarding_status():
    """Check if onboarding has been completed."""
    if deps.db is None:
        return {"completed": False}
    completed = deps.db.get_user_state('onboarding_completed', '0')
    return {"completed": completed == '1'}


@router.post("/api/onboarding-status")
async def set_onboarding_status(req: OnboardingStatusRequest):
    """Mark onboarding as completed — requires speaker enrollment."""
    if deps.db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if req.completed:
        # Validate speaker enrollment before marking complete
        if deps.orchestrator and deps.orchestrator.speaker_verifier:
            status = deps.orchestrator.speaker_verifier.get_status()
            if not status.get('enrolled', False):
                raise HTTPException(
                    status_code=400,
                    detail="Speaker enrollment must be completed before finishing onboarding"
                )

    deps.db.set_user_state('onboarding_completed', '1' if req.completed else '0')
    return {"success": True}


@router.get("/api/quest/first-light")
async def get_first_light_quest():
    """First Light quest — removed. Stub returns show=false for backwards compat."""
    return {"show": False}


@router.post("/api/quest/first-light/complete")
async def complete_first_light_task(req: FirstLightTaskRequest):
    """First Light quest — removed. Stub returns success for backwards compat."""
    return {"success": True}


@router.get("/api/config")
async def get_config():
    """Serve runtime configuration to frontend."""
    from app_config import config as cfg
    return {
        'api_port': cfg.api_port,
        'speech_threshold_sec': cfg.preferred_speech_sec,
        'analysis_interval_sec': cfg.analysis_interval_sec,
        'zone_thresholds': {
            'stressed': cfg.stress_threshold_high,
            'tense': cfg.stress_threshold_med,
        },
        'zone_colors': {
            'calm': cfg.zone_calm,
            'steady': cfg.zone_steady,
            'tense': cfg.zone_tense,
            'stressed': cfg.zone_stressed,
        },
        'brand_colors': {
            'primary': cfg.brand_primary,
            'secondary': cfg.brand_secondary,
        },
    }
