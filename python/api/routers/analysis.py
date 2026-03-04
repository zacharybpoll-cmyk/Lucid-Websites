"""
Analysis, correlations, summaries, compass, capsules, echoes, recovery pulse.
"""
import logging
import threading
from fastapi import APIRouter
from datetime import datetime, date, timedelta
import json
import numpy as np

from api import dependencies as deps
from api.exceptions import DatabaseNotReady, ServiceNotReady
from api.schemas import IntentionRequest
from api.constants import ZONE_ORDER
from backend.pattern_detector import PatternDetector

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# EH-009: Circuit breaker for ML model / insight engine calls
# ---------------------------------------------------------------------------
_insight_failures = 0
_CIRCUIT_BREAKER_THRESHOLD = 3
_circuit_lock = threading.Lock()


async def _safe_insight_call(func, *args, **kwargs):
    """Call an insight engine function with circuit-breaker protection.

    After _CIRCUIT_BREAKER_THRESHOLD consecutive failures the breaker opens
    and subsequent calls return None immediately until a success resets it.
    """
    global _insight_failures
    with _circuit_lock:
        if _insight_failures >= _CIRCUIT_BREAKER_THRESHOLD:
            logger.warning("Circuit breaker open for insight engine (%d consecutive failures)", _insight_failures)
            return None
    try:
        result = func(*args, **kwargs)
        # Handle coroutines returned by async insight methods
        if hasattr(result, '__await__'):
            result = await result
        with _circuit_lock:
            _insight_failures = 0
        return result
    except Exception as e:
        with _circuit_lock:
            _insight_failures += 1
            logger.error("Insight engine error (%d/%d): %s", _insight_failures, _CIRCUIT_BREAKER_THRESHOLD, e)
        return None


@router.get("/api/trends")
async def get_trends(days: int = 14):
    """Get 14-day trends with score averages"""
    logger.debug("GET /api/trends")
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        summaries = deps.db.get_daily_summaries(days=days)

        # Compute trend direction from summaries
        trend_direction = 'stable'
        if len(summaries) >= 6:
            sorted_s = sorted(summaries, key=lambda s: s.get('date', ''), reverse=True)
            recent = sorted_s[:3]
            previous = sorted_s[3:6]
            recent_stress = sum(s.get('avg_stress', 50) or 50 for s in recent) / 3
            prev_stress = sum(s.get('avg_stress', 50) or 50 for s in previous) / 3
            diff = recent_stress - prev_stress
            if diff < -5:
                trend_direction = 'improving'
            elif diff > 5:
                trend_direction = 'declining'

        return {
            'daily_summaries': summaries,
            'trend_direction': trend_direction,
            'has_data': len(summaries) > 0,
        }
    except Exception as e:
        logger.warning("Error in /api/trends: %s", e)
        return {
            'daily_summaries': [],
            'trend_direction': 'stable',
            'has_data': False,
        }


@router.get("/api/history")
async def get_history(days: int = 30):
    """Get historical data with correlation matrix"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        # Get readings for last N days
        start_date = date.today() - timedelta(days=days)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()

        readings = deps.db.get_readings(start_time=start_time, limit=1000)

        # Compute correlation matrix using numpy
        correlation_matrix = {}

        if len(readings) > 1:
            # Extract numeric columns
            metrics = ['stress_score', 'wellbeing_score', 'activation_score', 'calm_score',
                       'depression_risk_score', 'anxiety_risk_score', 'emotional_stability_score',
                       'f0_mean', 'speech_rate']

            # Find metrics that exist in the data
            available_metrics = [
                m for m in metrics
                if any(r.get(m) is not None for r in readings)
            ]

            if len(available_metrics) > 1:
                # Only use readings where ALL available metrics are present
                valid_readings = [
                    r for r in readings
                    if all(r.get(m) is not None for m in available_metrics)
                ]

                if len(valid_readings) > 1:
                    data_array = np.array([
                        [r[m] for m in available_metrics]
                        for r in valid_readings
                    ])

                    # Remove zero-variance columns (cause NaN in correlation)
                    stds = data_array.std(axis=0)
                    non_const_mask = stds > 0
                    if non_const_mask.sum() > 1:
                        filtered_metrics = [m for m, keep in zip(available_metrics, non_const_mask) if keep]
                        filtered_data = data_array[:, non_const_mask]
                        corr_matrix = np.corrcoef(filtered_data.T)
                        # Replace any remaining NaN with 0
                        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

                        correlation_matrix = {
                            'labels': filtered_metrics,
                            'values': corr_matrix.tolist()
                        }

        return {
            'readings': readings,
            'correlation_matrix': correlation_matrix,
            'total_readings': len(readings),
            'days': days,
            'has_data': len(readings) > 0,
        }
    except Exception as e:
        logger.warning("Error in /api/history: %s", e)
        return {
            'readings': [],
            'correlation_matrix': {},
            'total_readings': 0,
            'days': days,
            'has_data': False,
        }


@router.get("/api/briefing")
async def get_briefing(type: str = "morning", force: bool = False):
    """Get or generate daily briefing (morning or evening)"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    today_str = date.today().isoformat()
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    # Force-regenerate: delete cached briefing first
    if force:
        deps.db.delete_briefing(today_str, type)

    # Check if already generated today
    if not force:
        existing = deps.db.get_briefing(today_str, type)
        if existing:
            # Try to parse as JSON (structured briefing); fall back to legacy string
            try:
                data = json.loads(existing)
                return {"type": type, "data": data, "cached": True}
            except (json.JSONDecodeError, TypeError):
                return {"type": type, "content": existing, "cached": True}

    # Generate new briefing (circuit-breaker protected)
    try:
        if type == "morning":
            yesterday_summary = deps.db.get_summary_for_date(yesterday)
            yesterday_readings = deps.db.get_readings_for_date(yesterday)
            content = await _safe_insight_call(
                deps.insight_engine.generate_morning_briefing,
                yesterday_str, yesterday_readings, yesterday_summary
            )
        else:  # evening
            today_summary = deps.db.compute_daily_summary()
            today_readings = deps.db.get_today_readings()
            content = await _safe_insight_call(
                deps.insight_engine.generate_evening_recap,
                today_summary, today_readings
            )

        if content is None:
            content = "Unable to generate briefing right now. Check back later."
    except Exception as e:
        logger.error("Failed to generate %s briefing: %s", type, e)
        content = "Unable to generate briefing right now. Check back later."

    # Only cache if we got real data (not a fallback)
    if isinstance(content, dict):
        if content.get('has_data'):
            deps.db.insert_briefing(today_str, type, json.dumps(content))
        return {"type": type, "data": content, "cached": False}
    else:
        # Evening recap still returns a string -- only cache non-fallback
        fallback_strings = [
            "Your day is just beginning. Check back this evening for a recap.",
            "Your day is complete. Rest well and recharge for tomorrow.",
            "Good morning! Start your day with intention and self-awareness.",
        ]
        if content not in fallback_strings:
            deps.db.insert_briefing(today_str, type, content)
        return {"type": type, "content": content, "cached": False}


@router.get("/api/morning-summary")
async def get_morning_summary():
    """Bundle Wellness Score + morning briefing + today's first reading for morning overlay"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    try:
        today_str = date.today().isoformat()
        yesterday = date.today() - timedelta(days=1)
        yesterday_str = yesterday.isoformat()

        # 1. Wellness Score
        wellness = deps.db.get_wellness_score(today_str)
        if not wellness:
            yesterday_summary = deps.db.get_summary_for_date(yesterday)
            wellness_result = deps.insight_engine.compute_wellness_score(deps.db, yesterday_summary)
        else:
            wellness_result = {'score': wellness.get('score', 0), 'has_data': True,
                             'profile': wellness.get('weight_profile'), 'date': today_str}

        # 2. Morning briefing (reuse cached if available)
        briefing_data = None
        existing = deps.db.get_briefing(today_str, 'morning')
        if existing:
            try:
                briefing_data = json.loads(existing)
            except (json.JSONDecodeError, TypeError):
                briefing_data = None

        if not briefing_data:
            yesterday_summary = deps.db.get_summary_for_date(yesterday)
            yesterday_readings = deps.db.get_readings_for_date(yesterday)
            briefing_data = await deps.insight_engine.generate_morning_briefing(
                yesterday_str, yesterday_readings, yesterday_summary
            )
            if isinstance(briefing_data, dict) and briefing_data.get('has_data'):
                deps.db.insert_briefing(today_str, 'morning', json.dumps(briefing_data))

        # 3. Voice Weather -- today's first reading
        voice_weather = None
        today_readings = deps.db.get_today_readings()
        if today_readings:
            first = today_readings[-1]  # oldest (list is DESC)
            voice_weather = {
                'zone': first.get('zone', 'steady'),
                'stress': round(first.get('stress_score', 0) or 0),
                'wellbeing': round(first.get('wellbeing_score') or first.get('mood_score', 50) or 50),
                'activation': round(first.get('activation_score') or first.get('energy_score', 50) or 50),
                'timestamp': first.get('timestamp', ''),
            }

        return {
            'wellness': wellness_result,
            'briefing': briefing_data,
            'voice_weather': voice_weather,
            'has_data': voice_weather is not None,
        }
    except Exception as e:
        logger.warning("Error in /api/morning-summary: %s", e)
        return {
            'wellness': {'score': 0, 'has_data': False},
            'briefing': None,
            'voice_weather': None,
            'has_data': False,
        }


@router.get("/api/evening-summary")
async def get_evening_summary():
    """Bundle today's stats for the 8 PM evening summary overlay"""
    logger.debug("GET /api/evening-summary")
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    _empty_evening = {
        'has_data': False,
        'wellness': {'score': 0, 'has_data': False},
        'wellness_delta': None,
        'avg_stress': None,
        'stress_delta': None,
        'time_in_calm_min': 0,
        'total_speech_min': 0,
        'reading_count': 0,
        'peak_stress_hour': None,
        'calm_peak_hour': None,
        'timeline': [],
        'insight': None,
    }

    try:
        result = deps.insight_engine.compute_evening_summary(deps.db)
        if result is None:
            return _empty_evening

        # Resolve wellness score async (circuit-breaker protected)
        wellness = await _safe_insight_call(deps.insight_engine.compute_intraday_wellness_score, deps.db)
        if wellness is None:
            wellness = {'score': None, 'has_data': False}

        wellness_delta = None
        wellness_yesterday = result.pop('wellness_yesterday', None)
        if wellness.get('has_data') and wellness_yesterday:
            wellness_delta = round(wellness.get('score', 0) - wellness_yesterday.get('score', 0))

        result['wellness'] = wellness
        result['wellness_delta'] = wellness_delta
        return result
    except Exception as e:
        logger.warning("Error in /api/evening-summary: %s", e)
        return _empty_evening


@router.get("/api/wellness")
async def get_wellness_score():
    """Get today's intraday Wellness Score (requires 1+ reading today)"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    result = await _safe_insight_call(deps.insight_engine.compute_intraday_wellness_score, deps.db)
    if result is None:
        return {'score': None, 'has_data': False}
    return result


@router.get("/api/recovery-pulse")
async def get_recovery_pulse():
    """Get recovery speed metrics for today's readings"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        readings = deps.db.get_today_readings()
    except Exception as e:
        logger.warning("Error in /api/recovery-pulse: %s", e)
        return {
            'readings': [],
            'avg_recovery_speed': 0,
            'trend': 'stable',
            'insight': 'Check in to start tracking your recovery',
            'has_data': False,
            'recovery_count': 0,
        }

    readings = readings or []

    # Sort chronologically (readings come DESC, we need ASC)
    readings_asc = sorted(readings, key=lambda r: r.get('timestamp', ''))

    # Build simplified reading list for sparkline
    sparkline_readings = []
    for r in readings_asc:
        stress = r.get('stress_score')
        ts = r.get('timestamp', '')
        if stress is not None and ts:
            try:
                t = datetime.fromisoformat(ts)
                sparkline_readings.append({
                    'stress': round(stress),
                    'time': t.strftime('%H:%M'),
                })
            except (ValueError, TypeError):
                pass

    if len(sparkline_readings) < 2:
        return {
            'readings': sparkline_readings,
            'avg_recovery_speed': 0,
            'trend': 'stable',
            'insight': 'Check in to start tracking your recovery' if len(sparkline_readings) == 0
                       else 'One more reading to see your recovery pulse',
            'has_data': len(sparkline_readings) > 0,
            'recovery_count': 0,
        }

    # Compute recovery events from today's readings
    today_drops = []
    for i in range(len(sparkline_readings) - 1):
        diff = sparkline_readings[i]['stress'] - sparkline_readings[i + 1]['stress']
        if diff > 0:
            today_drops.append(diff)

    today_avg = sum(today_drops) / len(today_drops) if today_drops else 0

    # 7-day historical comparison
    hist_drops = []
    try:
        start_date = date.today() - timedelta(days=7)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        end_time = datetime.combine(date.today(), datetime.min.time()).isoformat()
        hist_readings = deps.db.get_readings(start_time=start_time, end_time=end_time, limit=500)
        hist_asc = sorted(hist_readings, key=lambda r: r.get('timestamp', ''))
        for i in range(len(hist_asc) - 1):
            s_curr = hist_asc[i].get('stress_score')
            s_next = hist_asc[i + 1].get('stress_score')
            if s_curr is not None and s_next is not None:
                diff = s_curr - s_next
                if diff > 0:
                    hist_drops.append(diff)
    except Exception as e:
        logger.warning("Error computing historical recovery drops: %s", e)

    hist_avg = sum(hist_drops) / len(hist_drops) if hist_drops else 0

    # Determine trend
    if hist_avg > 0 and today_avg >= hist_avg * 1.1:
        trend = 'improving'
    elif hist_avg > 0 and today_avg <= hist_avg * 0.9:
        trend = 'declining'
    else:
        trend = 'stable'

    # Generate insight (AM vs PM comparison)
    insight = _generate_recovery_insight(sparkline_readings, today_drops)

    return {
        'readings': sparkline_readings,
        'avg_recovery_speed': round(today_avg),
        'trend': trend,
        'insight': insight,
        'has_data': True,
        'recovery_count': len(today_drops),
    }


def _generate_recovery_insight(readings, drops):
    """Generate contextual insight about recovery patterns"""
    if len(readings) < 3:
        return 'Keep checking in to build your recovery profile'
    if len(drops) == 0:
        return 'No stress dips yet \u2014 your levels have been rising or steady'
    if len(readings) < 6:
        return 'Your recovery speed is building'

    # AM vs PM comparison
    am_drops = []
    pm_drops = []
    for i in range(len(readings) - 1):
        diff = readings[i]['stress'] - readings[i + 1]['stress']
        if diff > 0:
            try:
                hour = int(readings[i]['time'].split(':')[0])
                if hour < 12:
                    am_drops.append(diff)
                else:
                    pm_drops.append(diff)
            except (ValueError, IndexError):
                pass

    if am_drops and pm_drops:
        am_avg = sum(am_drops) / len(am_drops)
        pm_avg = sum(pm_drops) / len(pm_drops)
        if am_avg > 0 and pm_avg > 0:
            ratio = max(am_avg, pm_avg) / min(am_avg, pm_avg)
            if ratio >= 1.5:
                faster = 'morning' if am_avg > pm_avg else 'afternoon'
                return f'You recover {ratio:.0f}x faster in the {faster}.'

    avg_drop = sum(drops) / len(drops)
    if avg_drop >= 15:
        return 'Strong recovery pattern \u2014 you bounce back quickly.'
    elif avg_drop >= 8:
        return 'Steady recovery \u2014 your stress resets between readings.'
    else:
        return 'Gradual recovery pattern building throughout the day.'


@router.get("/api/compass")
async def get_compass():
    """Get weekly compass direction"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    result = await _safe_insight_call(deps.insight_engine.compute_compass, deps.db)
    if result is None:
        return {'direction': 'steady', 'has_data': False}
    return result


@router.post("/api/compass/intention")
async def set_intention(req: IntentionRequest):
    """Set weekly intention"""
    if deps.db is None:
        raise DatabaseNotReady()
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    deps.db.set_compass_intention(week_start, req.intention)
    return {'success': True}


@router.get("/api/weekly-wrapped")
async def get_weekly_wrapped():
    """Get the latest weekly wrap summary"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    result = await _safe_insight_call(deps.insight_engine.generate_weekly_wrapped, deps.db)
    if result is None:
        return {'has_data': False}
    return result


@router.get("/api/capsules")
async def get_capsules():
    """Get time capsule messages"""
    if deps.db is None:
        raise DatabaseNotReady()
    if deps.insight_engine is None:
        raise ServiceNotReady("Insight engine")

    capsules = await _safe_insight_call(deps.insight_engine.check_time_capsules, deps.db)
    if capsules is None:
        return {'capsules': [], 'has_data': False}
    return {'capsules': capsules, 'has_data': len(capsules) > 0}


@router.get("/api/echoes")
async def get_echoes():
    """Get pattern discoveries"""
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        detector = PatternDetector(deps.db)
        new_discoveries = detector.detect_patterns()
    except Exception as e:
        logger.warning("Error detecting patterns: %s", e)
        new_discoveries = []

    try:
        echoes = deps.db.get_echoes(limit=20)
        unseen = deps.db.get_unseen_echo_count()
        deps.db.mark_echoes_seen()
    except Exception as e:
        logger.warning("Error fetching echoes: %s", e)
        echoes = []
        unseen = 0
    return {
        'echoes': echoes,
        'unseen_count': unseen,
        'new': new_discoveries,
        'has_data': len(echoes) > 0,
    }
