"""Voice Scan (Active Assessment) endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import dependencies as deps

router = APIRouter()


class ActiveStartRequest(BaseModel):
    prompt_text: str = ''


class ActiveNotesRequest(BaseModel):
    id: int
    notes: str


@router.post("/api/active/start")
async def active_start(req: ActiveStartRequest):
    """Start a voice scan recording session."""
    if deps.active_runner is None:
        raise HTTPException(status_code=503, detail="Active assessment not initialized")
    result = deps.active_runner.start_session(prompt_text=req.prompt_text)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@router.get("/api/active/status")
async def active_status():
    """Get current voice scan session status (polled by frontend)."""
    if deps.active_runner is None:
        return {'active': False}
    return deps.active_runner.get_session_status()


@router.post("/api/active/stop")
async def active_stop():
    """Stop recording and run analysis."""
    if deps.active_runner is None:
        raise HTTPException(status_code=503, detail="Active assessment not initialized")
    result = deps.active_runner.stop_session()
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@router.post("/api/active/cancel")
async def active_cancel():
    """Cancel the current voice scan session."""
    if deps.active_runner is None:
        return {'status': 'cancelled'}
    return deps.active_runner.cancel_session()


@router.get("/api/active/history")
async def active_history(limit: int = 20):
    """Get previous voice scan results."""
    if deps.db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return deps.db.get_active_assessments(limit=limit)


@router.get("/api/active/compare")
async def active_compare():
    """Compare latest voice scan vs recent passive readings."""
    if deps.db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    latest_scan = deps.db.get_latest_active_assessment()
    if latest_scan is None:
        return {'scan': None, 'passive_avg': None}

    recent = deps.db.get_readings(limit=20)
    if not recent:
        return {'scan': latest_scan, 'passive_avg': None}

    keys = ['depression_mapped', 'anxiety_mapped', 'stress_score', 'mood_score',
            'energy_score', 'calm_score', 'wellbeing_score', 'activation_score']
    passive_avg = {}
    for key in keys:
        vals = [r[key] for r in recent if r.get(key) is not None]
        passive_avg[key] = round(sum(vals) / len(vals), 1) if vals else None

    return {'scan': latest_scan, 'passive_avg': passive_avg}


@router.post("/api/active/notes")
async def active_update_notes(req: ActiveNotesRequest):
    """Update notes on a voice scan assessment."""
    if deps.db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    success = deps.db.update_active_assessment_notes(req.id, req.notes)
    if not success:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {'success': True}
