"""
FastAPI routes for Lucid
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from datetime import datetime
import numpy as np

# Global references (set by main.py)
db = None
orchestrator = None


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
from api.routers import lab as _lab_mod
from api.routers import voice_profile as _voice_profile_mod
from api.routers import reports as _reports_mod
from api.routers import analysis as _analysis_mod
from api.routers import dashboard as _dashboard_mod
from api.routers import speaker as _speaker_mod
from api.routers import active_assessment as _active_assessment_mod
from api.routers import engagement as _engagement_mod
from api.routers import clarity as _clarity_mod
app.include_router(_health_mod.router)
app.include_router(_readings_mod.router)
app.include_router(_settings_mod.router)
app.include_router(_lab_mod.router)
app.include_router(_voice_profile_mod.router)
app.include_router(_reports_mod.router)
app.include_router(_analysis_mod.router)
app.include_router(_dashboard_mod.router)
app.include_router(_speaker_mod.router)
app.include_router(_active_assessment_mod.router)
app.include_router(_engagement_mod.router)
app.include_router(_clarity_mod.router)

@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/static/index.html")


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



# Analytics router
from api.routers.analytics import router as analytics_router
app.include_router(analytics_router)

# Mount static files (frontend) - must be AFTER API routes
from pathlib import Path
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
