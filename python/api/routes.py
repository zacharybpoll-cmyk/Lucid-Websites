"""
FastAPI routes for Lucid
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
    TagRequest, TagResponse, MeetingToggleRequest,
    SelfAssessmentRequest, SelfAssessmentResponse,
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
active_runner = None

# Daily summary cache (avoids recomputing on every GET /api/today)
_daily_summary_cache = None
_daily_summary_reading_count = None

app = FastAPI(title="Lucid API")

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handler: converts LucidError subclasses to structured JSON 503s
from api.exceptions import LucidError as _LucidError

@app.exception_handler(_LucidError)
async def _lucid_error_handler(request, exc: _LucidError):
    from fastapi.responses import JSONResponse as _JR
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return _JR(
        status_code=exc.status_code,
        content={"error": exc.message, "code": exc.code, "retry_after": exc.retry_after},
        headers=headers,
    )

# Include new routers BEFORE legacy route definitions so they take precedence.
# New routers use api.dependencies globals (safe for test patching).
from api.routers import health as _health_mod
from api.routers import readings as _readings_mod
from api.routers import settings as _settings_mod
app.include_router(_health_mod.router)
app.include_router(_readings_mod.router)
app.include_router(_settings_mod.router)

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
            'wellbeing': latest.get('wellbeing_score') or latest.get('mood_score', 50),
            'activation': latest.get('activation_score') or latest.get('energy_score', 50),
            'emotional_stability': latest.get('emotional_stability_score', 50),
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
    if reading_count != _daily_summary_reading_count:
        _daily_summary_cache = db.compute_daily_summary()
        _daily_summary_reading_count = reading_count
    summary = _daily_summary_cache

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

@app.post("/api/self-assessment", response_model=SelfAssessmentResponse)
async def submit_self_assessment(request: SelfAssessmentRequest):
    """Submit a self-assessment of current zone (ground truth for calibration).

    Called when user responds to "How are you feeling?" prompt.
    Links to the nearest reading for comparison.
    """
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    valid_zones = {'calm', 'steady', 'tense', 'stressed'}
    if request.zone not in valid_zones:
        raise HTTPException(status_code=400, detail=f"Zone must be one of: {valid_zones}")

    # Link to nearest reading if not explicitly provided
    reading_id = request.reading_id
    if reading_id is None:
        reading_id = db.get_nearest_reading_id()

    assessment_id = db.insert_self_assessment(request.zone, reading_id)

    return {
        'id': assessment_id,
        'timestamp': datetime.now().isoformat(),
        'zone': request.zone,
        'reading_id': reading_id,
    }

@app.get("/api/self-assessment/status")
async def self_assessment_status():
    """Check if a self-assessment prompt should be shown.

    Returns whether enough time has passed since last assessment (>6 hours)
    and whether there are recent readings to compare against.
    """
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    last_time = db.get_last_self_assessment_time()
    should_prompt = True

    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            should_prompt = hours_since >= 6  # Prompt at most every 6 hours
        except (ValueError, TypeError):
            should_prompt = True

    nearest_reading_id = db.get_nearest_reading_id()

    return {
        'should_prompt': should_prompt,
        'last_assessment': last_time,
        'nearest_reading_id': nearest_reading_id,
    }

@app.get("/api/self-assessments")
async def get_self_assessments():
    """Get recent self-assessments for review/calibration."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    return db.get_self_assessments(limit=100)

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

# --- Diagnostic / Test Endpoints ---

@app.post("/api/test-analysis")
def test_analysis():
    """Run the full analysis pipeline on synthetic audio (no mic required).

    Generates 35s of speech-like audio, then runs:
    DAM inference → acoustic features → score computation → DB insert.
    Skips speaker verification (synthetic audio would fail it).
    Uses def (not async def) so FastAPI runs it in a threadpool for blocking DAM.
    """
    import traceback as tb
    import logging
    logger = logging.getLogger('lucid.test-analysis')

    if orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")
    if not orchestrator.models_ready.is_set():
        raise HTTPException(status_code=503, detail="Models not loaded yet")
    if orchestrator.dam_analyzer is None:
        raise HTTPException(status_code=503, detail="DAM model not available")

    # Acquire analysis lock (non-blocking)
    if not orchestrator._analysis_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Analysis already in progress")

    try:
        import app_config as config

        # Generate 35s of synthetic speech-like audio (harmonics + noise)
        duration = 35.0
        sr = config.SAMPLE_RATE
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
        # Fundamental frequency ~150Hz with harmonics (simulates voiced speech)
        audio = (
            0.3 * np.sin(2 * np.pi * 150 * t) +
            0.15 * np.sin(2 * np.pi * 300 * t) +
            0.08 * np.sin(2 * np.pi * 450 * t) +
            0.04 * np.sin(2 * np.pi * 600 * t)
        )
        # Add slight noise for realism
        audio += 0.02 * np.random.randn(len(t)).astype(np.float32)
        # Amplitude modulation (~4Hz) to simulate syllable rhythm
        audio *= (0.7 + 0.3 * np.sin(2 * np.pi * 4 * t))
        audio = audio.astype(np.float32)

        logger.info(f"Test analysis: generated {duration}s synthetic audio at {sr}Hz")

        # Step 1: DAM inference
        logger.info("Test analysis: running DAM inference...")
        dam_output = orchestrator.dam_analyzer.analyze(audio, sample_rate=sr)
        if dam_output is None:
            return {"success": False, "error": "DAM returned None"}
        logger.info(f"Test analysis: DAM output — dep_raw={dam_output.get('depression_raw'):.3f}, anx_raw={dam_output.get('anxiety_raw'):.3f}")

        # Step 2: Acoustic features
        logger.info("Test analysis: extracting acoustic features...")
        acoustic_features = orchestrator.feature_extractor.extract(audio)
        logger.info(f"Test analysis: features — f0_mean={acoustic_features.get('f0_mean', 0):.1f}Hz")

        # Step 3: Compute scores
        logger.info("Test analysis: computing scores...")
        scores = orchestrator.score_engine.compute_scores(dam_output, acoustic_features)
        logger.info(f"Test analysis: scores — stress={scores.get('stress_score', 0):.1f}, mood={scores.get('mood_score', 0):.1f}")

        # Step 4: Build reading dict and insert into DB
        reading = {}
        reading.update(dam_output)
        reading.update(acoustic_features)
        reading.update(scores)
        reading['timestamp'] = datetime.now().isoformat()
        reading['speech_duration_sec'] = duration
        reading['meeting_detected'] = 0
        reading['vad_confidence'] = 1.0
        reading['low_confidence'] = 0

        logger.info("Test analysis: inserting reading into DB...")
        reading_id = db.insert_reading(reading)
        db.compute_daily_summary()
        orchestrator._analysis_success_count += 1
        orchestrator._last_analysis_error = None
        logger.info(f"Test analysis: SUCCESS — saved reading #{reading_id}")

        return {
            "success": True,
            "reading_id": reading_id,
            "scores": {
                "stress": scores.get('stress_score'),
                "mood": scores.get('mood_score'),
                "energy": scores.get('energy_score'),
                "calm": scores.get('calm_score'),
            },
            "dam_output": {
                "depression_raw": dam_output.get('depression_raw'),
                "anxiety_raw": dam_output.get('anxiety_raw'),
                "depression_mapped": dam_output.get('depression_mapped'),
                "anxiety_mapped": dam_output.get('anxiety_mapped'),
            },
        }
    except Exception as e:
        logger.error(f"Test analysis FAILED: {e}")
        logger.error(tb.format_exc())
        return {
            "success": False,
            "error": str(e),
            "traceback": tb.format_exc(),
        }
    finally:
        orchestrator._analysis_lock.release()

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


# ============ Wellness Score (Feature #1) ============

@app.get("/api/morning-summary")
async def get_morning_summary():
    """Bundle Wellness Score + morning briefing + today's first reading for morning overlay"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    today_str = date.today().isoformat()
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    # 1. Wellness Score
    wellness = db.get_wellness_score(today_str)
    if not wellness:
        yesterday_summary = db.get_summary_for_date(yesterday)
        wellness_result = insight_engine.compute_wellness_score(db, yesterday_summary)
    else:
        wellness_result = {'score': wellness['score'], 'has_data': True,
                         'profile': wellness['weight_profile'], 'date': today_str}

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
        'wellness': wellness_result,
        'briefing': briefing_data,
        'voice_weather': voice_weather,
    }


@app.get("/api/evening-summary")
async def get_evening_summary():
    """Bundle today's stats for the 8 PM evening summary overlay"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    today_str = date.today().isoformat()
    yesterday = date.today() - timedelta(days=1)

    # 1. Today's aggregate
    today_summary = db.compute_daily_summary()

    # 2. Wellness score (intraday)
    wellness = insight_engine.compute_intraday_wellness_score(db)

    # 3. Yesterday for comparison
    yesterday_summary = db.get_summary_for_date(yesterday)
    wellness_yesterday = db.get_wellness_score(yesterday.isoformat())

    # 4. Compact readings for mini-timeline (stress per 30-min bucket, 6 AM - 8 PM)
    today_readings = db.get_today_readings()
    buckets = {}
    for r in today_readings:
        try:
            ts = datetime.fromisoformat(r['timestamp'])
            hour_bucket = ts.hour + (0.5 if ts.minute >= 30 else 0)
            if 6 <= hour_bucket < 20:
                if hour_bucket not in buckets:
                    buckets[hour_bucket] = []
                buckets[hour_bucket].append({
                    'stress': r.get('stress_score', 50) or 50,
                    'zone': r.get('zone', 'steady') or 'steady'
                })
        except Exception:
            pass
    timeline = [
        {
            'hour': h,
            'stress': round(sum(v['stress'] for v in vs) / len(vs)),
            'zone': max(set(v['zone'] for v in vs), key=lambda z: ['calm','steady','tense','stressed'].index(z) if z in ['calm','steady','tense','stressed'] else 0)
        }
        for h, vs in sorted(buckets.items())
    ]

    # 5. Peak stress hour
    peak_hour = None
    peak_stress = 0
    for r in today_readings:
        s = r.get('stress_score', 0) or 0
        if s > peak_stress:
            peak_stress = s
            try:
                ts = datetime.fromisoformat(r['timestamp'])
                peak_hour = ts.strftime('%-I %p')
            except Exception:
                peak_hour = None

    # 6. Calm peak hour (lowest avg stress hour with data)
    hourly_stress = {}
    for r in today_readings:
        try:
            ts = datetime.fromisoformat(r['timestamp'])
            h = ts.hour
            if h not in hourly_stress:
                hourly_stress[h] = []
            hourly_stress[h].append(r.get('stress_score', 50) or 50)
        except Exception:
            pass
    calm_hour = None
    if hourly_stress:
        best_h = min(hourly_stress, key=lambda h: sum(hourly_stress[h])/len(hourly_stress[h]))
        calm_hour = f"{best_h % 12 or 12}–{(best_h+1) % 12 or 12} {'AM' if best_h < 12 else 'PM'}"

    # 7. Comparison deltas
    wellness_delta = None
    stress_delta = None
    if wellness.get('has_data') and wellness_yesterday:
        wellness_delta = round(wellness['score'] - wellness_yesterday['score'])
    if today_summary and yesterday_summary:
        today_stress = today_summary.get('avg_stress') or 0
        yest_stress = yesterday_summary.get('avg_stress') or 0
        if today_stress and yest_stress:
            stress_delta = round(today_stress - yest_stress)

    # 8. Insight line
    insight = None
    if calm_hour and peak_hour:
        insight = f"Your calmest hour was {calm_hour}. Stress peaked around {peak_hour}."
    elif calm_hour:
        insight = f"Your calmest period was {calm_hour}."
    elif today_summary:
        calm_min = today_summary.get('time_in_calm_min', 0) or 0
        if calm_min >= 60:
            insight = f"You spent {round(calm_min / 60, 1)} hours in a calm state today."

    return {
        'has_data': len(today_readings) >= 1,
        'wellness': wellness,
        'wellness_delta': wellness_delta,
        'avg_stress': round(today_summary.get('avg_stress') or 0) if today_summary else None,
        'stress_delta': stress_delta,
        'time_in_calm_min': round(today_summary.get('time_in_calm_min') or 0) if today_summary else 0,
        'total_speech_min': round(today_summary.get('total_speech_min') or 0) if today_summary else 0,
        'reading_count': len(today_readings),
        'peak_stress_hour': peak_hour,
        'calm_peak_hour': calm_hour,
        'timeline': timeline,
        'insight': insight,
    }


@app.get("/api/wellness")
async def get_wellness_score():
    """Get today's intraday Wellness Score with delta, trend, and top contributor"""
    if db is None or insight_engine is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    result = insight_engine.compute_intraday_wellness_score(db)

    # Yesterday's score for delta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yesterday_wellness = db.get_wellness_score(yesterday)
    result['yesterday_score'] = yesterday_wellness['score'] if yesterday_wellness else None

    # 7-day trend direction
    try:
        bc = BurnoutCalculator(db)
        risk_data = bc.calculate_burnout_risk()
        result['trend_direction'] = risk_data.get('trend_direction', 'stable')
    except Exception:
        result['trend_direction'] = 'stable'

    # Top contributor to wellness score
    if result.get('has_data'):
        result['top_contributor'] = insight_engine.get_top_wellness_contributor(db)

    return result

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

# ============ Recovery Pulse ============

@app.get("/api/recovery-pulse")
async def get_recovery_pulse():
    """Get recovery speed metrics for today's readings"""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    readings = db.get_today_readings()

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
        hist_readings = db.get_readings(start_time=start_time, end_time=end_time, limit=500)
        hist_asc = sorted(hist_readings, key=lambda r: r.get('timestamp', ''))
        for i in range(len(hist_asc) - 1):
            s_curr = hist_asc[i].get('stress_score')
            s_next = hist_asc[i + 1].get('stress_score')
            if s_curr is not None and s_next is not None:
                diff = s_curr - s_next
                if diff > 0:
                    hist_drops.append(diff)
    except Exception:
        pass

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
        return 'No stress dips yet — your levels have been rising or steady'
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
        return 'Strong recovery pattern — you bounce back quickly.'
    elif avg_drop >= 8:
        return 'Steady recovery — your stress resets between readings.'
    else:
        return 'Gradual recovery pattern building throughout the day.'


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
    from api import dependencies as _deps
    effective_db = _deps.db if _deps.db is not None else db
    if effective_db is None:
        return {'zone': 'idle', 'stress': 0, 'last_reading': None, 'has_data': False}

    readings = effective_db.get_today_readings()
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
        'has_data': True,
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


# ============ Phase 1/2/3 Insight Endpoints ============

@app.get("/api/insights/meeting-vs-nonmeeting")
async def get_meeting_vs_nonmeeting():
    """Compare average stress/mood during meetings vs. non-meeting time (last 30 days)."""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    start_date = date.today() - timedelta(days=30)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
    readings = db.get_readings(start_time=start_time, limit=5000)

    if not readings:
        return {'has_data': False, 'meeting': {}, 'non_meeting': {}, 'delta': {}}

    meeting_stress, meeting_mood, non_stress, non_mood = [], [], [], []
    for r in readings:
        is_mtg = r.get('meeting_detected', 0) == 1
        s = r.get('stress_score')
        m = r.get('mood_score')
        if s is not None:
            (meeting_stress if is_mtg else non_stress).append(s)
        if m is not None:
            (meeting_mood if is_mtg else non_mood).append(m)

    def safe_avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    mtg_s = safe_avg(meeting_stress)
    mtg_m = safe_avg(meeting_mood)
    non_s = safe_avg(non_stress)
    non_m = safe_avg(non_mood)
    delta_s = round(mtg_s - non_s, 1) if (mtg_s and non_s) else None

    return {
        'has_data': True,
        'meeting': {'avg_stress': mtg_s, 'avg_mood': mtg_m, 'reading_count': len(meeting_stress)},
        'non_meeting': {'avg_stress': non_s, 'avg_mood': non_m, 'reading_count': len(non_stress)},
        'delta': {
            'stress': delta_s,
            'mood': round(mtg_m - non_m, 1) if (mtg_m and non_m) else None,
            'interpretation': (
                f"Meetings raise stress by {abs(delta_s):.0f} points" if delta_s and delta_s > 3
                else "Meetings have minimal stress impact" if delta_s is not None
                else "Not enough data"
            ),
        },
        'period_days': 30,
    }


@app.get("/api/insights/topic-stress")
async def get_topic_stress():
    """Per-topic stress delta vs. baseline over last 90 days."""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    start_date = date.today() - timedelta(days=90)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
    readings = db.get_readings(start_time=start_time, limit=10000)

    if not readings:
        return {'has_data': False, 'topics': {}, 'baseline_stress': None}

    all_stress = [r['stress_score'] for r in readings if r.get('stress_score') is not None]
    if not all_stress:
        return {'has_data': False, 'topics': {}, 'baseline_stress': None}

    baseline = sum(all_stress) / len(all_stress)
    threshold = 0.3
    topic_stress = {'work': [], 'relationships': [], 'health': []}

    for r in readings:
        s = r.get('stress_score')
        if s is None:
            continue
        if (r.get('topic_work_score') or 0) > threshold:
            topic_stress['work'].append(s)
        if (r.get('topic_relationships_score') or 0) > threshold:
            topic_stress['relationships'].append(s)
        if (r.get('topic_health_score') or 0) > threshold:
            topic_stress['health'].append(s)

    topic_deltas = {}
    for topic, scores in topic_stress.items():
        if len(scores) >= 3:
            avg = sum(scores) / len(scores)
            topic_deltas[topic] = {
                'delta': round(avg - baseline, 1),
                'avg_stress': round(avg, 1),
                'reading_count': len(scores),
            }

    return {
        'has_data': bool(topic_deltas),
        'topics': topic_deltas,
        'baseline_stress': round(baseline, 1),
        'period_days': 90,
    }


@app.get("/api/insights/vocabulary-trend")
async def get_vocabulary_trend():
    """Rolling lexical diversity trend with alogia flag."""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    start_date = date.today() - timedelta(days=60)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
    readings = db.get_readings(start_time=start_time, limit=5000)

    lex_readings = [r for r in readings if (r.get('lexical_diversity') or 0) > 0]
    if len(lex_readings) < 7:
        return {'has_data': False, 'trend': [], 'baseline': None, 'alogia_flag': False}

    all_lex = [r['lexical_diversity'] for r in lex_readings]
    baseline = sum(all_lex) / len(all_lex)
    variance = sum((x - baseline) ** 2 for x in all_lex) / len(all_lex)
    std = variance ** 0.5 if variance > 0 else 0.01

    from collections import defaultdict
    daily = defaultdict(list)
    for r in lex_readings:
        try:
            daily[r['timestamp'][:10]].append(r['lexical_diversity'])
        except (KeyError, TypeError):
            continue

    trend = []
    for day in sorted(daily.keys())[-14:]:
        day_avg = sum(daily[day]) / len(daily[day])
        z = (day_avg - baseline) / std if std > 0 else 0
        trend.append({'date': day, 'avg': round(day_avg, 3), 'z_score': round(z, 2)})

    alogia_flag = (len(trend) >= 5 and all(d['z_score'] < -2.0 for d in trend[-5:]))

    return {
        'has_data': True,
        'trend': trend,
        'baseline': round(baseline, 3),
        'std': round(std, 3),
        'alogia_flag': alogia_flag,
    }


@app.get("/api/export/therapist-summary")
async def export_therapist_summary(days: int = 30):
    """Structured therapist-ready summary of acoustic + linguistic patterns."""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    start_date = date.today() - timedelta(days=days)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
    readings = db.get_readings(start_time=start_time, limit=10000)

    if not readings:
        return {'period': f'{start_date.isoformat()} to {date.today().isoformat()}', 'has_data': False, 'reading_count': 0}

    def avg(lst):
        filtered = [x for x in lst if x is not None]
        return round(sum(filtered) / len(filtered), 1) if filtered else None

    acoustic_summary = {
        'avg_stress': avg([r.get('stress_score') for r in readings]),
        'avg_mood': avg([r.get('mood_score') for r in readings]),
        'avg_energy': avg([r.get('energy_score') for r in readings]),
        'avg_calm': avg([r.get('calm_score') for r in readings]),
        'avg_f0': avg([r.get('f0_mean') for r in readings]),
        'avg_hnr': avg([r.get('hnr') for r in readings]),
        'avg_shimmer': avg([r.get('shimmer') for r in readings]),
    }

    ling_readings = [r for r in readings if r.get('filler_rate') is not None]
    dominant_topic = None
    if ling_readings:
        topic_avgs = {
            'work': avg([r.get('topic_work_score', 0) for r in ling_readings]) or 0,
            'relationships': avg([r.get('topic_relationships_score', 0) for r in ling_readings]) or 0,
            'health': avg([r.get('topic_health_score', 0) for r in ling_readings]) or 0,
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

    zone_counts = {}
    for r in readings:
        z = r.get('zone', 'unknown')
        zone_counts[z] = zone_counts.get(z, 0) + 1
    total = max(1, len(readings))
    zone_distribution = {z: round(c / total, 3) for z, c in zone_counts.items()}

    flags = []
    lex_vals = [r['lexical_diversity'] for r in readings if r.get('lexical_diversity')]
    if len(lex_vals) >= 10:
        bl = sum(lex_vals) / len(lex_vals)
        sd = (sum((x - bl) ** 2 for x in lex_vals) / len(lex_vals)) ** 0.5 or 0.01
        if all((x - bl) / sd < -2.0 for x in lex_vals[:5]):
            flags.append('vocabulary_decline_sustained')
    stress_vals = [r['stress_score'] for r in readings if r.get('stress_score') is not None]
    if stress_vals:
        s_avg = sum(stress_vals) / len(stress_vals)
        if s_avg > 65:
            flags.append('sustained_elevated_stress')
        elif s_avg > 55:
            flags.append('moderately_elevated_stress')
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


@app.get("/api/settings/linguistic-analysis")
async def get_linguistic_analysis_setting():
    """Get the enhanced linguistic analysis preference."""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    value = db.get_user_state('linguistic_analysis_enhanced', 'true')
    return {'enabled': value.lower() == 'true'}


@app.post("/api/settings/linguistic-analysis")
async def set_linguistic_analysis_setting(request: Request):
    """Set the enhanced linguistic analysis preference."""
    if db is None:
        raise HTTPException(status_code=500, detail="Not initialized")
    body = await request.json()
    enabled = bool(body.get('enabled', True))
    db.set_user_state('linguistic_analysis_enhanced', 'true' if enabled else 'false')
    return {'success': True, 'enabled': enabled}


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
async def get_api_token(request: Request):
    """Get or generate the API token (for settings display)"""
    # Only allow from localhost
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Token endpoint is localhost-only")

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


# ============ First Light Quest ============

FIRST_LIGHT_TASKS = ['wellness', 'rings', 'grove', 'faq', 'trends']

@app.get("/api/quest/first-light")
async def get_first_light_quest():
    """Get First Light quest state."""
    if db is None:
        return {"show": False}

    onboarding = db.get_user_state('onboarding_completed', '0')
    if onboarding != '1':
        return {"show": False}

    completed = db.get_user_state('first_light_completed', '0') == '1'
    tasks = {}
    for task in FIRST_LIGHT_TASKS:
        tasks[task] = db.get_user_state(f'first_light_task_{task}', '0') == '1'

    return {"show": True, "tasks": tasks, "completed": completed}


class FirstLightTaskRequest(BaseModel):
    task: str

@app.post("/api/quest/first-light/complete")
async def complete_first_light_task(req: FirstLightTaskRequest):
    """Mark a First Light quest task as complete."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")

    if req.task not in FIRST_LIGHT_TASKS:
        raise HTTPException(status_code=400, detail="Invalid task name")

    # Mark task complete
    db.set_user_state(f'first_light_task_{req.task}', '1')

    # Check if all tasks are now complete
    all_done = all(
        db.get_user_state(f'first_light_task_{t}', '0') == '1'
        for t in FIRST_LIGHT_TASKS
    )

    just_completed = False
    if all_done and db.get_user_state('first_light_completed', '0') != '1':
        db.set_user_state('first_light_completed', '1')
        just_completed = True

        # Plant a bonus grove tree (stage 3 = blooming)
        today_str = date.today().isoformat()
        db.add_grove_tree(today_str, 'growing', 3)
        db.update_grove_tree(today_str, stage=3)

        # Award +2 rainfall
        current_rainfall = int(db.get_user_state('rainfall', '0'))
        db.set_user_state('rainfall', str(current_rainfall + 2))

    return {"success": True, "just_completed": just_completed}


# ============ Voice Scan (Active Assessment) ============

class ActiveStartRequest(BaseModel):
    prompt_text: str = ''

class ActiveNotesRequest(BaseModel):
    id: int
    notes: str

@app.post("/api/active/start")
async def active_start(req: ActiveStartRequest):
    """Start a voice scan recording session."""
    if active_runner is None:
        raise HTTPException(status_code=503, detail="Active assessment not initialized")
    result = active_runner.start_session(prompt_text=req.prompt_text)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    return result

@app.get("/api/active/status")
async def active_status():
    """Get current voice scan session status (polled by frontend)."""
    if active_runner is None:
        return {'active': False}
    return active_runner.get_session_status()

@app.post("/api/active/stop")
async def active_stop():
    """Stop recording and run analysis."""
    if active_runner is None:
        raise HTTPException(status_code=503, detail="Active assessment not initialized")
    result = active_runner.stop_session()
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    return result

@app.post("/api/active/cancel")
async def active_cancel():
    """Cancel the current voice scan session."""
    if active_runner is None:
        return {'status': 'cancelled'}
    return active_runner.cancel_session()

@app.get("/api/active/history")
async def active_history(limit: int = 20):
    """Get previous voice scan results."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return db.get_active_assessments(limit=limit)

@app.get("/api/active/compare")
async def active_compare():
    """Compare latest voice scan vs recent passive readings."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    latest_scan = db.get_latest_active_assessment()
    if latest_scan is None:
        return {'scan': None, 'passive_avg': None}

    # Get recent passive readings (last 24 hours)
    recent = db.get_readings(limit=20)
    if not recent:
        return {'scan': latest_scan, 'passive_avg': None}

    # Compute averages of key scores
    keys = ['depression_mapped', 'anxiety_mapped', 'stress_score', 'mood_score',
            'energy_score', 'calm_score', 'wellbeing_score', 'activation_score']
    passive_avg = {}
    for key in keys:
        vals = [r[key] for r in recent if r.get(key) is not None]
        passive_avg[key] = round(sum(vals) / len(vals), 1) if vals else None

    return {'scan': latest_scan, 'passive_avg': passive_avg}

@app.post("/api/active/notes")
async def active_update_notes(req: ActiveNotesRequest):
    """Update notes on a voice scan assessment."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    success = db.update_active_assessment_notes(req.id, req.notes)
    if not success:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {'success': True}


# Analytics router
from api.routers.analytics import router as analytics_router
app.include_router(analytics_router)

# Mount static files (frontend) - must be AFTER API routes
from pathlib import Path
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
