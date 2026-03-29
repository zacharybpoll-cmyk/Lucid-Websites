"""
Dashboard layout, engagement, export, rings, beacon, meeting toggle.
"""
import logging
import time
from fastapi import APIRouter
from fastapi.responses import Response
from datetime import datetime, date, timedelta

from api import dependencies as deps
from api.exceptions import DatabaseNotReady, ServiceNotReady
from api.schemas import (
    MeetingToggleRequest, LayoutRequest,
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
        summary = {'milestones': [], 'has_data': False}
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


@router.get("/api/insights/meeting-vs-nonmeeting")
async def get_meeting_vs_nonmeeting():
    """Compare average stress/mood during meetings vs. non-meeting time.

    Returns delta scores and 30-day trend.
    """
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        start_date = date.today() - timedelta(days=30)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        readings = deps.db.get_readings(start_time=start_time, limit=5000)

        if not readings:
            return {'has_data': False, 'meeting': {}, 'non_meeting': {}, 'delta': {}}

        meeting_stress = []
        meeting_mood = []
        non_stress = []
        non_mood = []

        for r in readings:
            is_meeting = r.get('meeting_detected', 0) == 1
            s = r.get('stress_score')
            m = r.get('mood_score')
            if s is not None:
                (meeting_stress if is_meeting else non_stress).append(s)
            if m is not None:
                (meeting_mood if is_meeting else non_mood).append(m)

        def safe_avg(lst):
            return round(sum(lst) / len(lst), 1) if lst else None

        mtg_stress = safe_avg(meeting_stress)
        mtg_mood = safe_avg(meeting_mood)
        non_mtg_stress = safe_avg(non_stress)
        non_mtg_mood = safe_avg(non_mood)

        delta_stress = round(mtg_stress - non_mtg_stress, 1) if (mtg_stress and non_mtg_stress) else None
        delta_mood = round(mtg_mood - non_mtg_mood, 1) if (mtg_mood and non_mtg_mood) else None

        return {
            'has_data': True,
            'meeting': {
                'avg_stress': mtg_stress,
                'avg_mood': mtg_mood,
                'reading_count': len(meeting_stress),
            },
            'non_meeting': {
                'avg_stress': non_mtg_stress,
                'avg_mood': non_mtg_mood,
                'reading_count': len(non_stress),
            },
            'delta': {
                'stress': delta_stress,
                'mood': delta_mood,
                'interpretation': (
                    f"Meetings raise stress by {abs(delta_stress):.0f} points"
                    if delta_stress and delta_stress > 3
                    else "Meetings have minimal stress impact"
                    if delta_stress is not None
                    else "Not enough data"
                ),
            },
            'period_days': 30,
        }
    except Exception as e:
        logger.warning("Error in /api/insights/meeting-vs-nonmeeting: %s", e)
        return {'has_data': False, 'error': str(e)}


@router.get("/api/insights/topic-stress")
async def get_topic_stress():
    """Compute per-topic average stress delta vs. baseline over last 90 days.

    Returns stress delta for work, relationships, and health topic buckets.
    """
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        start_date = date.today() - timedelta(days=90)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        readings = deps.db.get_readings(start_time=start_time, limit=10000)

        if not readings:
            return {'has_data': False, 'topics': {}, 'baseline_stress': None}

        # Compute baseline (all readings with stress score)
        all_stress = [r['stress_score'] for r in readings if r.get('stress_score') is not None]
        if not all_stress:
            return {'has_data': False, 'topics': {}, 'baseline_stress': None}

        baseline = sum(all_stress) / len(all_stress)

        threshold = 0.3  # Topic must be dominant to count

        topic_stress = {
            'work': [],
            'relationships': [],
            'health': [],
        }

        for r in readings:
            s = r.get('stress_score')
            if s is None:
                continue
            if r.get('topic_work_score', 0) and r['topic_work_score'] > threshold:
                topic_stress['work'].append(s)
            if r.get('topic_relationships_score', 0) and r['topic_relationships_score'] > threshold:
                topic_stress['relationships'].append(s)
            if r.get('topic_health_score', 0) and r['topic_health_score'] > threshold:
                topic_stress['health'].append(s)

        topic_deltas = {}
        for topic, scores in topic_stress.items():
            if len(scores) >= 3:  # Need at least 3 readings
                avg = sum(scores) / len(scores)
                delta = round(avg - baseline, 1)
                topic_deltas[topic] = {
                    'delta': delta,
                    'avg_stress': round(avg, 1),
                    'reading_count': len(scores),
                }

        return {
            'has_data': bool(topic_deltas),
            'topics': topic_deltas,
            'baseline_stress': round(baseline, 1),
            'period_days': 90,
        }
    except Exception as e:
        logger.warning("Error in /api/insights/topic-stress: %s", e)
        return {'has_data': False, 'error': str(e)}


@router.get("/api/insights/vocabulary-trend")
async def get_vocabulary_trend():
    """Track rolling 7-day lexical diversity vs. personal baseline.

    A sustained drop >2σ below baseline over 5+ days may indicate alogia.
    """
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        start_date = date.today() - timedelta(days=60)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        readings = deps.db.get_readings(start_time=start_time, limit=5000)

        lex_readings = [r for r in readings if r.get('lexical_diversity') is not None
                        and r['lexical_diversity'] > 0]

        if len(lex_readings) < 7:
            return {'has_data': False, 'trend': [], 'baseline': None, 'alogia_flag': False}

        all_lex = [r['lexical_diversity'] for r in lex_readings]
        baseline = sum(all_lex) / len(all_lex)
        n = len(all_lex)
        variance = sum((x - baseline) ** 2 for x in all_lex) / n
        std = variance ** 0.5 if variance > 0 else 0.01

        # Build daily averages for last 14 days
        from collections import defaultdict
        daily = defaultdict(list)
        for r in lex_readings:
            try:
                day = r['timestamp'][:10]
                daily[day].append(r['lexical_diversity'])
            except (KeyError, TypeError):
                continue

        trend = []
        for day in sorted(daily.keys())[-14:]:
            day_avg = sum(daily[day]) / len(daily[day])
            z = (day_avg - baseline) / std if std > 0 else 0
            trend.append({
                'date': day,
                'avg': round(day_avg, 3),
                'z_score': round(z, 2),
            })

        # Alogia flag: last 5 days all below -2σ
        alogia_flag = False
        if len(trend) >= 5:
            recent_5 = trend[-5:]
            if all(d['z_score'] < -2.0 for d in recent_5):
                alogia_flag = True

        return {
            'has_data': True,
            'trend': trend,
            'baseline': round(baseline, 3),
            'std': round(std, 3),
            'alogia_flag': alogia_flag,
        }
    except Exception as e:
        logger.warning("Error in /api/insights/vocabulary-trend: %s", e)
        return {'has_data': False, 'error': str(e)}


@router.get("/api/export/therapist-summary")
async def export_therapist_summary(days: int = 30):
    """Export structured therapist-ready summary of acoustic + linguistic patterns.

    Returns JSON with acoustic summary, linguistic summary, longitudinal flags,
    and zone distribution for the specified period.
    """
    if deps.db is None:
        raise DatabaseNotReady()

    try:
        start_date = date.today() - timedelta(days=days)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        end_time = datetime.now().isoformat()
        readings = deps.db.get_readings(start_time=start_time, limit=10000)

        if not readings:
            return {
                'period': f'{start_date.isoformat()} to {date.today().isoformat()}',
                'has_data': False,
                'reading_count': 0,
            }

        def avg(lst):
            filtered = [x for x in lst if x is not None]
            return round(sum(filtered) / len(filtered), 1) if filtered else None

        # Acoustic summary
        acoustic_summary = {
            'avg_stress': avg([r.get('stress_score') for r in readings]),
            'avg_mood': avg([r.get('mood_score') for r in readings]),
            'avg_energy': avg([r.get('energy_score') for r in readings]),
            'avg_calm': avg([r.get('calm_score') for r in readings]),
            'avg_f0': avg([r.get('f0_mean') for r in readings]),
            'avg_hnr': avg([r.get('hnr') for r in readings]),
            'avg_shimmer': avg([r.get('shimmer') for r in readings]),
        }

        # Linguistic summary
        ling_readings = [r for r in readings if r.get('filler_rate') is not None]
        dominant_topic = None
        if ling_readings:
            work_avg = avg([r.get('topic_work_score', 0) for r in ling_readings])
            rel_avg = avg([r.get('topic_relationships_score', 0) for r in ling_readings])
            health_avg = avg([r.get('topic_health_score', 0) for r in ling_readings])
            topic_avgs = {
                'work': work_avg or 0,
                'relationships': rel_avg or 0,
                'health': health_avg or 0,
            }
            dominant_topic = max(topic_avgs, key=lambda k: topic_avgs[k])

        linguistic_summary = {
            'avg_filler_rate': avg([r.get('filler_rate') for r in ling_readings]),
            'avg_hedging_score': avg([r.get('hedging_score') for r in ling_readings]),
            'avg_negative_sentiment': avg([r.get('negative_sentiment') for r in ling_readings]),
            'avg_lexical_diversity': avg([r.get('lexical_diversity') for r in ling_readings]),
            'avg_pronoun_i_ratio': avg([r.get('pronoun_i_ratio') for r in ling_readings]),
            'avg_absolutist_ratio': avg([r.get('absolutist_ratio') for r in ling_readings]),
            'avg_sentiment_valence': avg([r.get('sentiment_valence') for r in ling_readings]),
            'avg_sentiment_arousal': avg([r.get('sentiment_arousal') for r in ling_readings]),
            'dominant_topic': dominant_topic,
            'linguistic_reading_count': len(ling_readings),
        }

        # Zone distribution
        zone_counts = {}
        for r in readings:
            z = r.get('zone', 'unknown')
            zone_counts[z] = zone_counts.get(z, 0) + 1
        total = max(1, len(readings))
        zone_distribution = {z: round(c / total, 3) for z, c in zone_counts.items()}

        # Longitudinal flags
        flags = []

        # Check vocabulary trend (alogia signal)
        lex_vals = [r['lexical_diversity'] for r in readings if r.get('lexical_diversity')]
        if len(lex_vals) >= 10:
            baseline_lex = sum(lex_vals) / len(lex_vals)
            variance_lex = sum((x - baseline_lex) ** 2 for x in lex_vals) / len(lex_vals)
            std_lex = variance_lex ** 0.5 if variance_lex > 0 else 0.01
            recent = lex_vals[:5]  # most recent first
            if all((x - baseline_lex) / std_lex < -2.0 for x in recent):
                flags.append('vocabulary_decline_sustained')

        # Check sustained stress elevation
        stress_vals = [r['stress_score'] for r in readings if r.get('stress_score') is not None]
        if len(stress_vals) >= 5:
            stress_avg = sum(stress_vals) / len(stress_vals)
            if stress_avg > 65:
                flags.append('sustained_elevated_stress')
            elif stress_avg > 55:
                flags.append('moderately_elevated_stress')

        # Check absolutist language trend
        abs_vals = [r.get('absolutist_ratio', 0) for r in ling_readings if r.get('absolutist_ratio') is not None]
        if abs_vals and sum(abs_vals) / len(abs_vals) > 0.06:
            flags.append('elevated_absolutist_language')

        return {
            'period': f'{start_date.isoformat()} to {date.today().isoformat()}',
            'has_data': True,
            'reading_count': len(readings),
            'acoustic_summary': acoustic_summary,
            'linguistic_summary': linguistic_summary,
            'zone_distribution': zone_distribution,
            'longitudinal_flags': flags,
        }
    except Exception as e:
        logger.warning("Error in /api/export/therapist-summary: %s", e)
        return {'has_data': False, 'error': str(e)}
