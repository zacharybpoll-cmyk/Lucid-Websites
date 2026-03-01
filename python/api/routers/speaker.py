"""
Speaker verification endpoints: enroll, complete, status, delete, reset.
"""
from fastapi import APIRouter, HTTPException, Request
import numpy as np

from api import dependencies as deps

router = APIRouter()


@router.post("/api/speaker/enroll")
async def enroll_speaker_sample(request: Request):
    """Receive an enrollment audio sample and extract embedding.
    Expects raw audio bytes (16-bit PCM, 16kHz mono) with mood_label query param.
    """
    if deps.orchestrator is None or deps.orchestrator.speaker_verifier is None:
        raise HTTPException(
            status_code=503,
            detail="Models still loading \u2014 please wait",
            headers={"Retry-After": "5"},
        )

    mood_label = request.query_params.get('mood_label', 'neutral')
    body = await request.body()

    if len(body) < 1600:  # Less than 0.05s of audio
        raise HTTPException(status_code=400, detail="Audio too short")

    # Convert raw PCM bytes to float32 numpy array
    audio = np.frombuffer(body, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        embedding = deps.orchestrator.speaker_verifier.enroll_sample(audio, mood_label)
        samples = deps.db.get_enrollment_samples() if deps.db else []
        return {
            'success': True,
            'mood_label': mood_label,
            'embedding_dim': len(embedding),
            'total_samples': len(samples),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/speaker/enroll/complete")
async def complete_enrollment():
    """Compute centroid from enrollment samples and activate speaker verification."""
    if deps.orchestrator is None or deps.orchestrator.speaker_verifier is None:
        raise HTTPException(
            status_code=503,
            detail="Models still loading \u2014 please wait",
            headers={"Retry-After": "5"},
        )

    # Verify minimum enrollment samples
    samples = deps.db.get_enrollment_samples() if deps.db else []
    if len(samples) < 3:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 3 enrollment samples, have {len(samples)}"
        )

    try:
        centroid = deps.orchestrator.speaker_verifier.complete_enrollment()
        # Activate speaker gate in orchestrator
        deps.orchestrator.on_enrollment_complete()
        return {
            'success': True,
            'enrolled': True,
            'embedding_dim': len(centroid),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/speaker/status")
async def get_speaker_status():
    """Get speaker enrollment status."""
    if deps.orchestrator is None or deps.orchestrator.speaker_verifier is None:
        return {
            'enrolled': False,
            'model_loaded': False,
            'threshold': 0.45,
            'enrollment_samples': 0,
        }

    return deps.orchestrator.speaker_verifier.get_status()


@router.delete("/api/speaker/profile")
async def delete_speaker_profile():
    """Delete voice profile and return to unfiltered mode."""
    if deps.orchestrator is None or deps.orchestrator.speaker_verifier is None:
        raise HTTPException(
            status_code=503,
            detail="Models still loading \u2014 please wait",
            headers={"Retry-After": "5"},
        )

    deps.orchestrator.speaker_verifier.delete_profile()
    # Deactivate speaker gate in orchestrator
    deps.orchestrator.on_profile_deleted()
    if deps.db:
        deps.db.clear_enrollment_samples()
    return {'success': True, 'enrolled': False}


@router.post("/api/speaker/enroll/reset")
async def reset_enrollment():
    """Clear enrollment samples (for re-enrollment)."""
    if deps.db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    deps.db.clear_enrollment_samples()
    return {'success': True, 'samples_cleared': True}
