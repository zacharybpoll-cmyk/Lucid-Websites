"""
Feedback router — POST /api/feedback endpoint.
Stores user feedback (rating + optional comment + optional NPS) via analytics engine.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional, Literal

router = APIRouter()


class FeedbackRequest(BaseModel):
    rating: Literal["love_it", "its_okay", "not_for_me"]
    comment: Optional[str] = None
    nps_score: Optional[int] = None


@router.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest, request: Request):
    """Store user feedback via analytics engine."""
    import api.dependencies as deps
    if deps.analytics_engine is None:
        return {"status": "disabled"}

    payload = {"rating": req.rating}
    if req.comment:
        payload["comment"] = req.comment[:1000]  # Truncate long comments
    if req.nps_score is not None:
        payload["nps_score"] = max(0, min(10, req.nps_score))

    deps.analytics_engine.track("feedback", payload)
    return {"status": "ok"}
