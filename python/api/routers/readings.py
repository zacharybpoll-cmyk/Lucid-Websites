"""
Core data endpoints: today, readings, summaries, insight, tags, first-spark.
"""
import logging
import threading
from fastapi import APIRouter
from typing import List

from api import dependencies as deps
from api.exceptions import DatabaseNotReady, ServiceNotReady
from api.schemas import (
    Reading, DailySummary, TodayResponse,
    TagRequest, TagResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Daily summary cache (avoids recomputing on every GET /api/today)
_daily_summary_cache = None
_daily_summary_reading_count = None
_daily_summary_lock = threading.Lock()


@router.get("/api/today", response_model=TodayResponse)
async def get_today():
    """Get today's data: current scores, readings, and summary"""
    logger.debug("GET /api/today")
    if deps.db is None:
        raise DatabaseNotReady()

    # Get today's readings
    readings = deps.db.get_today_readings()

    # Calculate current scores (from most recent reading)
    current_scores = {
        'mood': 50,
        'stress': 50,
        'energy': 50,
        'calm': 50,
        'depression': 0,  # Keep 0 for clinical scores
        'anxiety': 0       # Keep 0 for clinical scores
    }

    if readings:
        latest = readings[0]  # Most recent (DESC order)
        # Use mapped PHQ-9 score (0-27) if available, fall back to raw
        try:
            dep_mapped = latest.get('depression_mapped')
            if dep_mapped is not None:
                depression_pct = min(100, max(0, dep_mapped / 27 * 100))
            else:
                depression_pct = min(100, max(0, latest.get('depression_raw', 0)) / 27 * 100)

            anx_mapped = latest.get('anxiety_mapped')
            if anx_mapped is not None:
                anxiety_pct = min(100, max(0, anx_mapped / 21 * 100))
            else:
                anxiety_pct = min(100, max(0, latest.get('anxiety_raw', 0) or 0) / 21 * 100)
        except (TypeError, ZeroDivisionError) as e:
            logger.warning("Error computing clinical scores: %s", e)
            depression_pct = 0
            anxiety_pct = 0

        current_scores = {
            'mood': latest.get('mood_score', 50),
            'stress': latest.get('stress_score', 50),
            'energy': latest.get('energy_score', 50),
            'calm': latest.get('calm_score', 50),
            'wellbeing': latest.get('wellbeing_score') or latest.get('mood_score', 50),
            'activation': latest.get('activation_score') or latest.get('energy_score', 50),
            'depression_risk': latest.get('depression_risk_score', 0),
            'anxiety_risk': latest.get('anxiety_risk_score', 0),
            'emotional_stability': latest.get('emotional_stability_score', 75),
            'depression': depression_pct,
            'anxiety': anxiety_pct,
            'depression_mapped': latest.get('depression_mapped'),
            'anxiety_mapped': latest.get('anxiety_mapped'),
            'depression_ci_lower': latest.get('depression_ci_lower'),
            'depression_ci_upper': latest.get('depression_ci_upper'),
            'anxiety_ci_lower': latest.get('anxiety_ci_lower'),
            'anxiety_ci_upper': latest.get('anxiety_ci_upper'),
            'uncertainty_flag': latest.get('uncertainty_flag'),
            'score_inconsistency': latest.get('score_inconsistency', 0),
            'vad_confidence': latest.get('vad_confidence'),
            'low_confidence': latest.get('low_confidence', 0),
        }

    # Get daily summary (cached if reading count unchanged)
    global _daily_summary_cache, _daily_summary_reading_count
    reading_count = len(readings)
    with _daily_summary_lock:
        if reading_count != _daily_summary_reading_count:
            try:
                _daily_summary_cache = deps.db.compute_daily_summary()
            except Exception as e:
                logger.warning("Failed to compute daily summary: %s", e)
                _daily_summary_cache = None
            _daily_summary_reading_count = reading_count
        summary = _daily_summary_cache

    # Get calibration status (EH-007: graceful degradation)
    try:
        if deps.orchestrator:
            calibration_status = deps.orchestrator.calibrator.get_calibration_status()
        else:
            calibration_status = {'is_calibrated': False}
    except Exception as e:
        logger.warning("Failed to get calibration status: %s", e)
        calibration_status = {'is_calibrated': False}

    # FS-011: Flag provisional baseline when not yet calibrated but readings exist
    if not calibration_status.get('is_calibrated') and readings:
        calibration_status['provisional'] = True
        calibration_status['readings_toward_calibration'] = len(readings)

    # Get all-time reading count for hero card logic
    try:
        with deps.db.lock:
            cursor = deps.db.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM readings")
            total_readings = cursor.fetchone()['cnt']
    except (AttributeError, KeyError) as e:
        logger.warning("Error fetching total reading count: %s", e)
        total_readings = len(readings)

    return {
        'current_scores': current_scores,
        'readings': readings,
        'summary': summary if summary else None,
        'calibration_status': calibration_status,
        'total_readings': total_readings
    }


@router.get("/api/readings")
async def get_readings(limit: int = 100):
    """Get recent readings"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        readings = deps.db.get_readings(limit=limit)
        return readings
    except Exception as e:
        logger.warning("Error in /api/readings: %s", e)
        return []


@router.get("/api/summaries")
async def get_summaries(days: int = 14):
    """Get daily summaries for the last N days"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        summaries = deps.db.get_daily_summaries(days=days)
        return summaries
    except Exception as e:
        logger.warning("Error in /api/summaries: %s", e)
        return []


@router.get("/api/insight")
async def get_insight():
    """Generate contextual insight from today's data"""
    logger.debug("GET /api/insight")
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    readings = deps.db.get_today_readings()
    summary = deps.db.compute_daily_summary()
    status = deps.orchestrator.get_status() if deps.orchestrator else {}

    try:
        result = await deps.insight_engine.generate_insight(readings, summary, status)
    except Exception as e:
        logger.error("Failed to generate insight: %s", e)
        result = {
            'insight': 'Unable to generate insight right now. Keep checking in.',
            'type': 'fallback',
        }
    return result


@router.post("/api/tag", response_model=TagResponse)
async def add_tag(tag: TagRequest):
    """Add a tag/annotation"""
    if deps.db is None:
        raise DatabaseNotReady()

    tag_id = deps.db.add_tag(tag.timestamp, tag.label, tag.notes or "")

    return {
        'id': tag_id,
        'timestamp': tag.timestamp,
        'label': tag.label,
        'notes': tag.notes
    }


@router.get("/api/tags")
async def get_tags():
    """Get recent tags"""
    if deps.db is None:
        raise DatabaseNotReady()

    tags = deps.db.get_tags()
    return tags


@router.get("/api/first-spark")
async def get_first_spark():
    """Get first-reading interpretation and journey progress"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    readings = deps.db.get_readings(limit=1000)
    total_readings = len(readings)

    if total_readings == 0:
        return {
            'has_readings': False,
            'has_data': False,
            'total_readings': 0,
            'show_journey': True,
        }

    # Get first-reading narrative if under calibration threshold
    result = {
        'has_readings': True,
        'has_data': True,
        'total_readings': total_readings,
        'show_journey': total_readings < 50,
    }

    if total_readings <= 10:
        try:
            latest = readings[0]
            spark = deps.insight_engine.interpret_first_reading(latest)
            result['narrative'] = spark.get('narrative')
            result['stress_percentile'] = spark.get('stress_percentile')
            result['percentile_text'] = spark.get('percentile_text')
            result['unlocks'] = spark.get('unlocks')
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Failed to interpret first reading: %s", e)
            result['narrative'] = 'Welcome to Attune. Keep checking in to build your voice profile.'

    # Determine which unlocks are achieved
    try:
        summaries = deps.db.get_daily_summaries(days=90)
        total_days = len(summaries)
    except Exception as e:
        logger.warning("Failed to get daily summaries for unlocks: %s", e)
        total_days = 0
    result['days_active'] = total_days
    result['unlocked'] = {
        'personalized': total_days >= 3,
        'patterns': total_days >= 7,
        'deep_insights': total_days >= 14,
        'trajectory': total_days >= 30,
    }

    return result
