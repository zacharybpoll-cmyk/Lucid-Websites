"""
Analytics router — POST /api/track endpoint.
Fire-and-forget: enqueues events for batched Supabase writes.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter()


class TrackRequest(BaseModel):
    event_type: str
    payload: Optional[Dict[str, Any]] = None


@router.post("/api/track")
async def track_event(req: TrackRequest, request: Request):
    """Enqueue an analytics event. Returns immediately (fire-and-forget)."""
    import api.dependencies as deps
    if deps.analytics_engine is None:
        return {"status": "disabled"}

    if req.event_type == "error":
        deps.analytics_engine.track_error(
            error_type=req.payload.get("error_type", "unknown") if req.payload else "unknown",
            error_message=req.payload.get("error_message", "") if req.payload else "",
            context=req.payload.get("context", "") if req.payload else "",
        )
    else:
        deps.analytics_engine.track(req.event_type, req.payload)

    return {"status": "ok"}
