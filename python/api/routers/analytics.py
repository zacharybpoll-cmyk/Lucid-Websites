"""
Analytics router — POST /api/track and GET /api/analytics/retention endpoints.
Fire-and-forget: enqueues events for batched Supabase writes.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta

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


@router.get("/api/analytics/retention")
async def get_retention(request: Request):
    """Return retention stats from Supabase analytics_daily table."""
    import api.dependencies as deps
    if deps.analytics_engine is None:
        return {"status": "disabled"}

    client = deps.analytics_engine._client
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    try:
        # DAU: distinct users with activity today
        dau_resp = client.client.table("analytics_daily").select(
            "user_id", count="exact"
        ).eq("date", today).execute()
        dau = dau_resp.count or 0

        # WAU: distinct users with activity in last 7 days
        week_ago = (now - timedelta(days=7)).date().isoformat()
        wau_resp = client.client.table("analytics_daily").select(
            "user_id", count="exact"
        ).gte("date", week_ago).execute()
        wau = wau_resp.count or 0

        # MAU: distinct users with activity in last 30 days
        month_ago = (now - timedelta(days=30)).date().isoformat()
        mau_resp = client.client.table("analytics_daily").select(
            "user_id", count="exact"
        ).gte("date", month_ago).execute()
        mau = mau_resp.count or 0

        return {
            "status": "ok",
            "dau": dau,
            "wau": wau,
            "mau": mau,
            "as_of": today,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
