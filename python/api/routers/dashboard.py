"""
Dashboard layout, engagement, export, grove, waypoints, rings, beacon, meeting toggle.
"""
import logging
import time
from fastapi import APIRouter
from fastapi.responses import Response
from datetime import datetime, date, timedelta

from api import dependencies as deps
from api.exceptions import DatabaseNotReady, ServiceNotReady
from api.schemas import (
    MeetingToggleRequest, ReviveRequest, LayoutRequest,
)
from backend.engagement import EngagementTracker

logger = logging.getLogger(__name__)

router = APIRouter()

# Cached EngagementTracker singleton (stateless — just holds db ref)
_tracker_cache = None
_tracker_cache_time = 0
_TRACKER_TTL = 30  # seconds


def _get_tracker():
    global _tracker_cache, _tracker_cache_time
    if deps.db is None:
        raise DatabaseNotReady()
    now = time.time()
    if _tracker_cache is None or (now - _tracker_cache_time) > _TRACKER_TTL:
        _tracker_cache = EngagementTracker(deps.db)
        _tracker_cache_time = now
    return _tracker_cache


@router.get("/api/engagement")
async def get_engagement():
    """Get engagement summary with streaks and milestones"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        tracker = _get_tracker()
        summary = tracker.get_engagement_summary()
        # FS-010: Add has_data so frontend knows whether to show "no data yet"
        summary['has_data'] = summary.get('total_readings', 0) > 0
    except Exception as e:
        logger.warning("Error computing engagement summary: %s", e)
        summary = {'streaks': {}, 'milestones': [], 'has_data': False}
    return summary


@router.get("/api/export/readings")
async def export_readings(start: str = None, end: str = None):
    """Export readings as CSV"""
    if deps.db is None:
        raise DatabaseNotReady()

    tracker = _get_tracker()
    csv_data = tracker.export_readings_csv(start, end)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=readings.csv"}
    )


@router.get("/api/export/summaries")
async def export_summaries(days: int = 30):
    """Export daily summaries as CSV"""
    if deps.db is None:
        raise DatabaseNotReady()

    tracker = _get_tracker()
    csv_data = tracker.export_summaries_csv(days)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=summaries.csv"}
    )


@router.get("/api/export/json")
async def export_json(days: int = 30):
    """Full JSON export of all readings, summaries, and scores"""
    if deps.db is None:
        raise DatabaseNotReady()

    start_date = date.today() - timedelta(days=days)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()

    readings = deps.db.get_readings(start_time=start_time, limit=10000)
    summaries = deps.db.get_daily_summaries(days=days)
    echoes = deps.db.get_echoes(limit=100)

    return {
        'export_date': datetime.now().isoformat(),
        'days': days,
        'readings': readings,
        'daily_summaries': summaries,
        'echoes': echoes,
        'total_readings': len(readings),
        'total_days': len(summaries),
    }


@router.post("/api/meeting/toggle")
async def toggle_meeting(request: MeetingToggleRequest):
    """Manually toggle meeting state"""
    if deps.meeting_detector is None:
        raise ServiceNotReady("Meeting detector")

    deps.meeting_detector.set_manual_override(request.active)

    if deps.orchestrator:
        deps.orchestrator.set_meeting_active(request.active)

    return {"status": "ok", "meeting_active": request.active}


@router.get("/api/grove")
async def get_grove():
    """Get grove state with trees"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        tracker = _get_tracker()
        return tracker.update_grove()
    except Exception as e:
        logger.warning("Error computing grove state: %s", e)
        return {'trees': [], 'has_data': False}


@router.post("/api/grove/revive")
async def revive_tree(req: ReviveRequest):
    """Use rainfall to revive a wilted tree"""
    if deps.db is None:
        raise DatabaseNotReady()
    tracker = _get_tracker()
    return tracker.revive_tree(req.date)


@router.get("/api/waypoints")
async def get_waypoints():
    """Get waypoints progression"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        tracker = _get_tracker()
        result = tracker.compute_waypoints()
        result['has_data'] = result.get('total_readings', 0) > 0
        return result
    except Exception as e:
        logger.warning("Error in /api/waypoints: %s", e)
        return {'waypoints': [], 'has_data': False}


@router.get("/api/rings")
async def get_rings():
    """Get today's rhythm ring progress"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        tracker = _get_tracker()
        result = tracker.compute_rhythm_rings()
        result['has_data'] = result.get('reading_count', 0) > 0
        return result
    except Exception as e:
        logger.warning("Error in /api/rings: %s", e)
        return {'rings': [], 'has_data': False}


@router.get("/api/beacon")
async def get_beacon():
    """Get current zone for menubar beacon display"""
    if deps.db is None:
        return {'zone': 'idle', 'stress': 0, 'last_reading': None, 'has_data': False}

    try:
        readings = deps.db.get_today_readings()
    except Exception as e:
        logger.warning("Error in /api/beacon: %s", e)
        return {'zone': 'idle', 'stress': 0, 'last_reading': None, 'has_data': False}

    if not readings:
        return {'zone': 'idle', 'stress': 0, 'last_reading': None, 'has_data': False}

    latest = readings[0]
    zone = latest.get('zone', 'steady')
    stress = latest.get('stress_score', 0) or 0
    ts = latest.get('timestamp', '')

    # Compute time ago
    time_ago = ''
    try:
        last_dt = datetime.fromisoformat(ts)
        diff = (datetime.now() - last_dt).total_seconds()
        if diff < 60:
            time_ago = 'just now'
        elif diff < 3600:
            time_ago = f'{int(diff / 60)}m ago'
        else:
            time_ago = f'{int(diff / 3600)}h ago'
    except (ValueError, TypeError):
        pass

    return {
        'zone': zone,
        'stress': round(stress),
        'last_reading': time_ago,
        'tooltip': f'{zone.title()} \u00b7 {round(stress)} stress \u00b7 {time_ago}',
        'has_data': True,
    }


@router.get("/api/layout")
async def get_layout():
    """Get dashboard card layout"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        layout = deps.db.get_dashboard_layout()
        return {'layout': layout, 'has_data': layout is not None}
    except Exception as e:
        logger.warning("Error in /api/layout: %s", e)
        return {'layout': None, 'has_data': False}


@router.put("/api/layout")
async def set_layout(req: LayoutRequest):
    """Save dashboard card layout"""
    if deps.db is None:
        raise DatabaseNotReady()
    deps.db.set_dashboard_layout(req.cards)
    return {'success': True}
