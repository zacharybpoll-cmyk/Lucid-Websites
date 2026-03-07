"""Clarity Journey endpoints: tracks, journey management, actions, progress."""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request

from api import dependencies as deps
from backend.clarity_engine import ClarityEngine

router = APIRouter()


def _engine() -> ClarityEngine:
    if deps.db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return ClarityEngine(deps.db)


@router.get("/api/clarity/tracks")
async def get_tracks():
    """Available tracks with current gauge scores."""
    return _engine().get_tracks_with_scores()


@router.post("/api/clarity/start")
async def start_journey(request: Request):
    """Start a new clarity journey."""
    body = await request.json()
    track = body.get('track')
    target_score = body.get('target_score')
    if not track or target_score is None:
        raise HTTPException(status_code=400, detail="track and target_score required")
    try:
        return _engine().start_journey(track, float(target_score))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/clarity/journey")
async def get_journey():
    """Active journey with full progress data."""
    engine = _engine()
    # Check for week advancement on load
    result = engine.advance_week()
    if result:
        return result
    progress = engine.get_journey_progress()
    if not progress:
        return {'active': False}
    return progress


@router.get("/api/clarity/progress-arc")
async def get_progress_arc():
    """Chart data: actuals vs projected trajectory."""
    return _engine().get_progress_arc_data()


@router.get("/api/clarity/today")
async def get_today():
    """Today's micro-action and summary."""
    engine = _engine()
    summary = engine.get_summary_for_dashboard()
    if not summary:
        return {'active': False}
    return summary


@router.post("/api/clarity/action/{action_id}/complete")
async def complete_action(action_id: int):
    """Mark an action as complete."""
    try:
        return _engine().complete_action(action_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/clarity/weekly-checkin")
async def trigger_weekly_checkin():
    """Trigger AI coach weekly check-in."""
    engine = _engine()
    journey = engine.get_active_journey()
    if not journey:
        raise HTTPException(status_code=404, detail="No active journey")

    # Generate check-in text via insight engine
    checkin_text = None
    if deps.insight_engine:
        try:
            progress = engine.get_journey_progress()
            checkin_text = await deps.insight_engine.generate_clarity_weekly_checkin(progress)
        except Exception:
            pass

    if not checkin_text:
        week = journey['current_week']
        checkin_text = f"Week {week} check-in: You're making progress on your {journey['track']} journey. Keep up the daily actions!"

    # Store in snapshot
    snapshots = deps.db.get_clarity_weekly_snapshots(journey['id'])
    current_snap = next((s for s in snapshots if s['week_number'] == journey['current_week']), None)
    if current_snap:
        with deps.db.lock:
            cursor = deps.db.conn.cursor()
            cursor.execute(
                "UPDATE clarity_weekly_snapshots SET coach_checkin_text = ?, coach_checkin_at = ? WHERE id = ?",
                (checkin_text, datetime.now().isoformat(), current_snap['id'])
            )
            deps.db.conn.commit()

    return {'checkin_text': checkin_text, 'week': journey['current_week']}


@router.get("/api/clarity/weekly-checkin/{week}")
async def get_weekly_checkin(week: int):
    """Get stored check-in for a specific week."""
    journey = _engine().get_active_journey()
    if not journey:
        raise HTTPException(status_code=404, detail="No active journey")
    snapshots = deps.db.get_clarity_weekly_snapshots(journey['id'])
    snap = next((s for s in snapshots if s['week_number'] == week), None)
    if not snap:
        return {'week': week, 'checkin_text': None}
    return {'week': week, 'checkin_text': snap.get('coach_checkin_text'), 'checkin_at': snap.get('coach_checkin_at')}


@router.post("/api/clarity/abandon")
async def abandon_journey():
    """Abandon the active journey."""
    success = _engine().abandon_journey()
    if not success:
        raise HTTPException(status_code=404, detail="No active journey to abandon")
    return {'success': True}


@router.get("/api/clarity/summary")
async def get_summary():
    """Lightweight summary for Today dashboard widget."""
    summary = _engine().get_summary_for_dashboard()
    if not summary:
        return {'active': False}
    return summary
