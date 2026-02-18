"""
FastAPI routes for Attune
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from typing import List
from datetime import datetime, date, timedelta
import json
import numpy as np
from pydantic import BaseModel
from api.schemas import (
    Reading, DailySummary, TodayResponse, StatusResponse,
    TagRequest, TagResponse, MeetingToggleRequest
)
from backend.burnout_calculator import BurnoutCalculator
from backend.engagement import EngagementTracker
from backend.pattern_detector import PatternDetector
from fastapi.responses import Response

# Global references (set by main.py)
db = None
orchestrator = None
meeting_detector = None
insight_engine = None
notification_manager = None

app = FastAPI(title="Attune API")

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/static/index.html")

@app.get("/api/health")
async def health():
    """Health check with model readiness status"""
    if orchestrator is None:
        return {"ready": False, "status": "initializing..."}

    models_loaded = orchestrator.models_ready.is_set()
    if models_loaded:
        return {"ready": True, "status": "ready"}
    else:
        return {"ready": False, "status": "loading models..."}

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Get current system status"""
    if orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    return orchestrator.get_status()

@app.get("/api/today", response_model=TodayResponse)
async def get_today():
    """Get today's data: current scores, readings, and summary"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    # Get today's readings
    readings = db.get_today_readings()

    # Calculate current scores (from most recent reading)
    current_scores = {
        'mood': 50,
        'stress': 50,
        'energy': 50,
        'calm': 50,
        'depression': 0,
        'anxiety': 0
    }

    if readings:
        latest = readings[0]  # Most recent (DESC order)
        # Use mapped PHQ-9 score (0-27) if available, fall back to raw
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

        current_scores = {
            'mood': latest.get('mood_score', 50),
            'stress': latest.get('stress_score', 50),
            'energy': latest.get('energy_score', 50),
            'calm': latest.get('calm_score', 50),
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

    # Get daily summary
    summary = db.compute_daily_summary()

    # Get calibration status
    if orchestrator:
        calibration_status = orchestrator.calibrator.get_calibration_status()
    else:
        calibration_status = {'is_calibrated': False}

    return {
        'current_scores': current_scores,
        'readings': readings,
        'summary': summary if summary else None,
        'calibration_status': calibration_status
    }

@app.get("/api/insight")
async def get_insight():
    """Generate contextual insight from today's data"""
    if insight_engine is None or db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    readings = db.get_today_readings()
    summary = db.compute_daily_summary()
    status = orchestrator.get_status() if orchestrator else {}

    result = await insight_engine.generate_insight(readings, summary, status)
    return result

@app.get("/api/readings", response_model=List[Reading])
async def get_readings(limit: int = 100):
    """Get recent readings"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    readings = db.get_readings(limit=limit)
    return readings

@app.get("/api/summaries", response_model=List[DailySummary])
async def get_summaries(days: int = 14):
    """Get daily summaries for the last N days"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    summaries = db.get_daily_summaries(days=days)
    return summaries

@app.get("/api/trends")
async def get_trends(days: int = 14):
    """Get 14-day trends with burnout risk analysis"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    summaries = db.get_daily_summaries(days=days)

    # Compute burnout risk
    burnout_calc = BurnoutCalculator(db)
    risk_data = burnout_calc.compute_burnout_risk(days=days)

    return {
        'daily_summaries': summaries,
        'burnout_risk': risk_data['burnout_risk'],
        'resilience_score': risk_data['resilience_score'],
        'trend_direction': risk_data['trend_direction'],
        'contributors': risk_data['contributors']
    }

@app.get("/api/briefing")
async def get_briefing(type: str = "morning", force: bool = False):
    """Get or generate daily briefing (morning or evening)"""
    if insight_engine is None or db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    today_str = date.today().isoformat()
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    # Force-regenerate: delete cached briefing first
    if force:
        db.delete_briefing(today_str, type)

    # Check if already generated today
    if not force:
        existing = db.get_briefing(today_str, type)
        if existing:
            # Try to parse as JSON (structured briefing); fall back to legacy string
            try:
                data = json.loads(existing)
                return {"type": type, "data": data, "cached": True}
            except (json.JSONDecodeError, TypeError):
                return {"type": type, "content": existing, "cached": True}

    # Generate new briefing
    if type == "morning":
        yesterday_summary = db.get_summary_for_date(yesterday)
        yesterday_readings = db.get_readings_for_date(yesterday)
        content = await insight_engine.generate_morning_briefing(yesterday_str, yesterday_readings, yesterday_summary)
    else:  # evening
        today_summary = db.compute_daily_summary()
        today_readings = db.get_today_readings()
        content = await insight_engine.generate_evening_recap(today_summary, today_readings)

    # Only cache if we got real data (not a fallback)
    if isinstance(content, dict):
        if content.get('has_data'):
            db.insert_briefing(today_str, type, json.dumps(content))
        return {"type": type, "data": content, "cached": False}
    else:
        # Evening recap still returns a string -- only cache non-fallback
        fallback_strings = [
            "Your day is just beginning. Check back this evening for a recap.",
            "Your day is complete. Rest well and recharge for tomorrow.",
            "Good morning! Start your day with intention and self-awareness.",
        ]
        if content not in fallback_strings:
            db.insert_briefing(today_str, type, content)
        return {"type": type, "content": content, "cached": False}

@app.post("/api/tag", response_model=TagResponse)
async def add_tag(tag: TagRequest):
    """Add a tag/annotation"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    tag_id = db.add_tag(tag.timestamp, tag.label, tag.notes or "")

    return {
        'id': tag_id,
        'timestamp': tag.timestamp,
        'label': tag.label,
        'notes': tag.notes
    }

@app.get("/api/tags", response_model=List[TagResponse])
async def get_tags():
    """Get recent tags"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    tags = db.get_tags()
    return tags

@app.post("/api/meeting/toggle")
async def toggle_meeting(request: MeetingToggleRequest):
    """Manually toggle meeting state"""
    if meeting_detector is None:
        raise HTTPException(status_code=500, detail="Meeting detector not initialized")

    meeting_detector.set_manual_override(request.active)

    if orchestrator:
        orchestrator.set_meeting_active(request.active)

    return {"status": "ok", "meeting_active": request.active}

@app.post("/api/pause")
async def pause_analysis():
    """Pause analysis"""
    if orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    orchestrator.pause()
    return {"status": "ok", "is_paused": True}

@app.post("/api/resume")
async def resume_analysis():
    """Resume analysis"""
    if orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    orchestrator.resume()
    return {"status": "ok", "is_paused": False}

# --- Engagement & Export Endpoints ---

@app.get("/api/engagement")
async def get_engagement():
    """Get engagement summary with streaks and milestones"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    tracker = EngagementTracker(db)
    summary = tracker.get_engagement_summary()
    return summary

@app.get("/api/export/readings")
async def export_readings(start: str = None, end: str = None):
    """Export readings as CSV"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    tracker = EngagementTracker(db)
    csv_data = tracker.export_readings_csv(start, end)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=readings.csv"}
    )

@app.get("/api/export/summaries")
async def export_summaries(days: int = 30):
    """Export daily summaries as CSV"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    tracker = EngagementTracker(db)
    csv_data = tracker.export_summaries_csv(days)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=summaries.csv"}
    )

@app.get("/api/history")
async def get_history(days: int = 30):
    """Get historical data with correlation matrix"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    # Get readings for last N days
    start_date = date.today() - timedelta(days=days)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()

    readings = db.get_readings(start_time=start_time, limit=1000)

    # Compute correlation matrix using numpy
    correlation_matrix = {}

    if len(readings) > 1:
        # Extract numeric columns
        metrics = ['stress_score', 'mood_score', 'energy_score', 'calm_score',
                   'depression_raw', 'anxiety_raw', 'f0_mean', 'speech_rate']

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
        'days': days
    }


# ============ Canopy Score (Feature #1) ============

@app.get("/api/morning-summary")
async def get_morning_summary():
    """Bundle Canopy Score + morning briefing + today's first reading for morning overlay"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    today_str = date.today().isoformat()
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    # 1. Canopy Score
    canopy = db.get_canopy_score(today_str)
    if not canopy:
        yesterday_summary = db.get_summary_for_date(yesterday)
        canopy_result = insight_engine.compute_canopy_score(db, yesterday_summary)
    else:
        canopy_result = {'score': canopy['score'], 'has_data': True,
                         'profile': canopy['weight_profile'], 'date': today_str}

    # 2. Morning briefing (reuse cached if available)
    briefing_data = None
    existing = db.get_briefing(today_str, 'morning')
    if existing:
        try:
            briefing_data = json.loads(existing)
        except (json.JSONDecodeError, TypeError):
            briefing_data = None

    if not briefing_data:
        yesterday_summary = db.get_summary_for_date(yesterday)
        yesterday_readings = db.get_readings_for_date(yesterday)
        briefing_data = await insight_engine.generate_morning_briefing(
            yesterday_str, yesterday_readings, yesterday_summary
        )
        if isinstance(briefing_data, dict) and briefing_data.get('has_data'):
            db.insert_briefing(today_str, 'morning', json.dumps(briefing_data))

    # 3. Voice Weather — today's first reading
    voice_weather = None
    today_readings = db.get_today_readings()
    if today_readings:
        first = today_readings[-1]  # oldest (list is DESC)
        voice_weather = {
            'zone': first.get('zone', 'steady'),
            'stress': round(first.get('stress_score', 0) or 0),
            'mood': round(first.get('mood_score', 50) or 50),
            'energy': round(first.get('energy_score', 50) or 50),
            'timestamp': first.get('timestamp', ''),
        }

    return {
        'canopy': canopy_result,
        'briefing': briefing_data,
        'voice_weather': voice_weather,
    }


@app.get("/api/canopy")
async def get_canopy_score():
    """Get today's intraday Canopy Score (requires 3+ readings today)"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    return insight_engine.compute_intraday_canopy_score(db)

# ============ Grove (Feature #2) ============

@app.get("/api/grove")
async def get_grove():
    """Get grove state with trees"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    tracker = EngagementTracker(db)
    return tracker.update_grove()

class ReviveRequest(BaseModel):
    date: str

@app.post("/api/grove/revive")
async def revive_tree(req: ReviveRequest):
    """Use rainfall to revive a wilted tree"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    tracker = EngagementTracker(db)
    return tracker.revive_tree(req.date)

# ============ Waypoints (Feature #4) ============

@app.get("/api/waypoints")
async def get_waypoints():
    """Get waypoints progression"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    tracker = EngagementTracker(db)
    return tracker.compute_waypoints()

# ============ Rhythm Rings (Feature #5) ============

@app.get("/api/rings")
async def get_rings():
    """Get today's rhythm ring progress"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    tracker = EngagementTracker(db)
    return tracker.compute_rhythm_rings()

# ============ Echoes (Feature #6) ============

@app.get("/api/echoes")
async def get_echoes():
    """Get pattern discoveries"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    detector = PatternDetector(db)
    new_discoveries = detector.detect_patterns()
    echoes = db.get_echoes(limit=20)
    unseen = db.get_unseen_echo_count()
    db.mark_echoes_seen()
    return {'echoes': echoes, 'unseen_count': unseen, 'new': new_discoveries}

# ============ Compass (Feature #7) ============

@app.get("/api/compass")
async def get_compass():
    """Get weekly compass direction"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    return insight_engine.compute_compass(db)

class IntentionRequest(BaseModel):
    intention: str

@app.post("/api/compass/intention")
async def set_intention(req: IntentionRequest):
    """Set weekly intention"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    db.set_compass_intention(week_start, req.intention)
    return {'success': True}

# ============ Time Capsule (Feature #9) ============

@app.get("/api/capsules")
async def get_capsules():
    """Get time capsule messages"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    capsules = insight_engine.check_time_capsules(db)
    return {'capsules': capsules}

# ============ Voice Garden / Dashboard Layout (Feature #10) ============

@app.get("/api/layout")
async def get_layout():
    """Get dashboard card layout"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    layout = db.get_dashboard_layout()
    return {'layout': layout}

class LayoutRequest(BaseModel):
    cards: list

@app.put("/api/layout")
async def set_layout(req: LayoutRequest):
    """Save dashboard card layout"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    db.set_dashboard_layout(req.cards)
    return {'success': True}


# ============ The Beacon — Current Zone Status ============

@app.get("/api/beacon")
async def get_beacon():
    """Get current zone for menubar beacon display"""
    if db is None:
        return {'zone': 'idle', 'stress': 0, 'last_reading': None}

    readings = db.get_today_readings()
    if not readings:
        return {'zone': 'idle', 'stress': 0, 'last_reading': None}

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
        'tooltip': f'{zone.title()} \u00B7 {round(stress)} stress \u00B7 {time_ago}'
    }


# ============ Weekly Wrapped ============

@app.get("/api/weekly-wrapped")
async def get_weekly_wrapped():
    """Get the latest weekly wrap summary"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    result = insight_engine.generate_weekly_wrapped(db)
    return result


# ============ First Spark — First Reading Interpretation ============

@app.get("/api/first-spark")
async def get_first_spark():
    """Get first-reading interpretation and journey progress"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    readings = db.get_readings(limit=1000)
    total_readings = len(readings)

    if total_readings == 0:
        return {
            'has_readings': False,
            'total_readings': 0,
            'show_journey': True,
        }

    # Get first-reading narrative if under calibration threshold
    result = {
        'has_readings': True,
        'total_readings': total_readings,
        'show_journey': total_readings < 50,
    }

    if total_readings <= 10:
        latest = readings[0]
        spark = insight_engine.interpret_first_reading(latest)
        result['narrative'] = spark['narrative']
        result['stress_percentile'] = spark['stress_percentile']
        result['percentile_text'] = spark['percentile_text']
        result['unlocks'] = spark['unlocks']

    # Determine which unlocks are achieved
    summaries = db.get_daily_summaries(days=90)
    total_days = len(summaries)
    result['days_active'] = total_days
    result['unlocked'] = {
        'personalized': total_days >= 3,
        'patterns': total_days >= 7,
        'deep_insights': total_days >= 14,
        'trajectory': total_days >= 30,
    }

    return result


# ============ Notification Preferences ============

@app.get("/api/notifications/prefs")
async def get_notification_prefs():
    """Get notification preferences"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    prefs = db.get_all_notification_prefs()
    # Fill defaults
    defaults = {
        'notifications_enabled': 'true',
        'quiet_start': '19',
        'quiet_end': '8',
        'notif_threshold': 'true',
        'notif_transition': 'true',
        'notif_milestone': 'true',
        'notif_echo': 'true',
        'notif_voice_weather': 'true',
        'notif_curtain_call': 'true',
        'notif_weekly_wrapped': 'true',
    }
    for k, v in defaults.items():
        if k not in prefs:
            prefs[k] = v
    return prefs


class NotifPrefRequest(BaseModel):
    key: str
    value: str

@app.post("/api/notifications/prefs")
async def set_notification_pref(req: NotifPrefRequest):
    """Set a notification preference"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    db.set_notification_pref(req.key, req.value)
    return {'success': True}


@app.get("/api/notifications/log")
async def get_notification_log(limit: int = 50):
    """Get recent notification history"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    return {'log': db.get_notification_log(limit=limit)}


# ============ The Bridge — Enhanced Export & Webhooks ============

@app.get("/api/export/json")
async def export_json(days: int = 30):
    """Full JSON export of all readings, summaries, and scores"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    start_date = date.today() - timedelta(days=days)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()

    readings = db.get_readings(start_time=start_time, limit=10000)
    summaries = db.get_daily_summaries(days=days)
    echoes = db.get_echoes(limit=100)

    return {
        'export_date': datetime.now().isoformat(),
        'days': days,
        'readings': readings,
        'daily_summaries': summaries,
        'echoes': echoes,
        'total_readings': len(readings),
        'total_days': len(summaries),
    }


class WebhookRequest(BaseModel):
    url: str
    trigger_type: str  # 'reading', 'zone_change'
    condition_field: str = None
    condition_op: str = None  # '>', '<', '>=', '<=', '=='
    condition_value: float = None

@app.post("/api/webhooks")
async def register_webhook(req: WebhookRequest):
    """Register a new webhook"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    webhook_id = db.add_webhook(
        url=req.url,
        trigger_type=req.trigger_type,
        condition_field=req.condition_field,
        condition_op=req.condition_op,
        condition_value=req.condition_value,
    )
    return {'success': True, 'id': webhook_id}


@app.get("/api/webhooks")
async def list_webhooks():
    """List all registered webhooks"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    return {'webhooks': db.get_webhooks(active_only=False)}


@app.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: int):
    """Delete a webhook"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    db.delete_webhook(webhook_id)
    return {'success': True}


# ============ v1 API — Token-authenticated public API ============

@app.get("/api/v1/readings")
async def api_v1_readings(request: Request, limit: int = 50):
    """Public-style API for readings with simple token auth"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    # Check API token
    token = request.headers.get('X-API-Token') or request.query_params.get('token')
    stored_token = db.get_user_state('api_token', '')
    if not stored_token:
        # Auto-generate token on first use
        import secrets
        stored_token = secrets.token_urlsafe(32)
        db.set_user_state('api_token', stored_token)

    if token != stored_token:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")

    readings = db.get_readings(limit=limit)
    return {'readings': readings, 'count': len(readings)}


@app.get("/api/v1/token")
async def get_api_token():
    """Get or generate the API token (for settings display)"""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    token = db.get_user_state('api_token', '')
    if not token:
        import secrets
        token = secrets.token_urlsafe(32)
        db.set_user_state('api_token', token)

    return {'token': token}


# ============ Speaker Verification ============

@app.post("/api/speaker/enroll")
async def enroll_speaker_sample(request: Request):
    """Receive an enrollment audio sample and extract embedding.
    Expects raw audio bytes (16-bit PCM, 16kHz mono) with mood_label query param.
    """
    if orchestrator is None or orchestrator.speaker_verifier is None:
        raise HTTPException(status_code=500, detail="Speaker verifier not initialized")

    mood_label = request.query_params.get('mood_label', 'neutral')
    body = await request.body()

    if len(body) < 1600:  # Less than 0.05s of audio
        raise HTTPException(status_code=400, detail="Audio too short")

    # Convert raw PCM bytes to float32 numpy array
    audio = np.frombuffer(body, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        embedding = orchestrator.speaker_verifier.enroll_sample(audio, mood_label)
        samples = db.get_enrollment_samples() if db else []
        return {
            'success': True,
            'mood_label': mood_label,
            'embedding_dim': len(embedding),
            'total_samples': len(samples),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/speaker/enroll/complete")
async def complete_enrollment():
    """Compute centroid from enrollment samples and activate speaker verification."""
    if orchestrator is None or orchestrator.speaker_verifier is None:
        raise HTTPException(status_code=500, detail="Speaker verifier not initialized")

    try:
        centroid = orchestrator.speaker_verifier.complete_enrollment()
        # Activate speaker gate in orchestrator
        orchestrator.on_enrollment_complete()
        return {
            'success': True,
            'enrolled': True,
            'embedding_dim': len(centroid),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/speaker/status")
async def get_speaker_status():
    """Get speaker enrollment status."""
    if orchestrator is None or orchestrator.speaker_verifier is None:
        return {
            'enrolled': False,
            'model_loaded': False,
            'threshold': 0.45,
            'enrollment_samples': 0,
        }

    return orchestrator.speaker_verifier.get_status()


@app.delete("/api/speaker/profile")
async def delete_speaker_profile():
    """Delete voice profile and return to unfiltered mode."""
    if orchestrator is None or orchestrator.speaker_verifier is None:
        raise HTTPException(status_code=500, detail="Speaker verifier not initialized")

    orchestrator.speaker_verifier.delete_profile()
    # Deactivate speaker gate in orchestrator
    orchestrator.on_profile_deleted()
    if db:
        db.clear_enrollment_samples()
    return {'success': True, 'enrolled': False}


@app.post("/api/speaker/enroll/reset")
async def reset_enrollment():
    """Clear enrollment samples (for re-enrollment)."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    db.clear_enrollment_samples()
    return {'success': True, 'samples_cleared': True}


# ============ Onboarding Status (Electron) ============

@app.get("/api/onboarding-status")
async def get_onboarding_status():
    """Check if onboarding has been completed."""
    if db is None:
        return {"completed": False}
    completed = db.get_user_state('onboarding_completed', '0')
    return {"completed": completed == '1'}

class OnboardingStatusRequest(BaseModel):
    completed: bool

@app.post("/api/onboarding-status")
async def set_onboarding_status(req: OnboardingStatusRequest):
    """Mark onboarding as completed."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    db.set_user_state('onboarding_completed', '1' if req.completed else '0')
    return {"success": True}


# Mount static files (frontend) - must be AFTER API routes
from pathlib import Path
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
