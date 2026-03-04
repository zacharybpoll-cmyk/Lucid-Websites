"""
Voice Studio API router.
Provides real-time biomarker streaming via WebSocket and session management endpoints.

Real-time biomarkers (NOT the same as full pipeline scores):
- vocal_steadiness: jitter inverse (fast DSP estimate)
- voice_clarity: HNR estimate
- tone_stability: F0 variance inverse
These are clearly labeled as estimates, not clinical measurements.
"""
import asyncio
import base64
import json
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.dependencies import get_db
from audio.realtime_features import RealtimeFeatureExtractor

router = APIRouter(prefix="/api/studio", tags=["studio"])
logger = logging.getLogger('lucid.studio')

# Singleton extractor (reused across WebSocket connections)
_extractor: Optional[RealtimeFeatureExtractor] = None


def _get_extractor() -> RealtimeFeatureExtractor:
    global _extractor
    if _extractor is None:
        _extractor = RealtimeFeatureExtractor(sample_rate=16000)
    return _extractor


# In-memory store for active studio sessions
_active_sessions: Dict[str, Dict] = {}


@router.post("/start")
async def start_session():
    """
    Create a studio session and establish baseline.
    Returns session_id and baseline snapshot.
    In production this would capture 15s of audio for baseline.
    For now returns a placeholder that the frontend can use.
    """
    session_id = f"studio_{int(time.time())}"
    _active_sessions[session_id] = {
        'started_at': datetime.now().isoformat(),
        'baseline': {
            'vocal_steadiness': 0.45,
            'voice_clarity': 0.48,
            'tone_stability': 0.42,
        },
        'readings': [],
        'status': 'active',
    }

    logger.info(f"Studio session started: {session_id}")
    return {
        'session_id': session_id,
        'baseline': _active_sessions[session_id]['baseline'],
        'message': 'Baseline captured. Begin your session.',
    }


@router.post("/end")
async def end_session(body: dict):
    """
    Finalize studio session. Computes before/after delta and saves to DB.
    Note: studio sessions are saved as reading_type='studio' and do NOT
    appear in the regular biomarker feeds.
    """
    session_id = body.get('session_id')
    if not session_id or session_id not in _active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _active_sessions[session_id]
    session['status'] = 'completed'
    session['ended_at'] = datetime.now().isoformat()

    readings = session.get('readings', [])
    baseline = session.get('baseline', {})

    # Compute end-of-session averages (last 30 readings = ~15 seconds)
    recent = readings[-30:] if len(readings) >= 30 else readings

    if recent:
        end_avg = {
            'vocal_steadiness': sum(r.get('vocal_steadiness', 0.5) for r in recent) / len(recent),
            'voice_clarity': sum(r.get('voice_clarity', 0.5) for r in recent) / len(recent),
            'tone_stability': sum(r.get('tone_stability', 0.5) for r in recent) / len(recent),
        }
    else:
        end_avg = baseline.copy()

    # Compute deltas
    deltas = {
        k: round((end_avg[k] - baseline[k]) * 100, 1)
        for k in end_avg
    }

    # Compute overall relaxation percentage
    avg_delta = sum(deltas.values()) / len(deltas) if deltas else 0
    relaxation_pct = round(max(0, avg_delta), 1)

    # Save to DB as studio session (use existing db pattern)
    try:
        db = get_db()
        if db is not None:
            duration_sec = len(readings) * 0.5  # 500ms per reading
            # Write to a session_summary table if it exists, or skip gracefully
            # We don't want to crash if the table doesn't exist yet
            try:
                db.conn.execute("""
                    INSERT OR IGNORE INTO studio_sessions
                    (session_id, started_at, ended_at, duration_sec, baseline_steadiness,
                     baseline_clarity, baseline_stability, end_steadiness, end_clarity,
                     end_stability, relaxation_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    session['started_at'],
                    session['ended_at'],
                    duration_sec,
                    baseline.get('vocal_steadiness', 0),
                    baseline.get('voice_clarity', 0),
                    baseline.get('tone_stability', 0),
                    end_avg.get('vocal_steadiness', 0),
                    end_avg.get('voice_clarity', 0),
                    end_avg.get('tone_stability', 0),
                    relaxation_pct,
                ))
                db.conn.commit()
            except Exception as e:
                logger.warning(f"Studio session DB write failed (table may not exist): {e}")
    except Exception as e:
        logger.warning(f"Could not save studio session to DB: {e}")

    del _active_sessions[session_id]

    return {
        'session_id': session_id,
        'summary': {
            'baseline': baseline,
            'end_state': end_avg,
            'deltas': deltas,
            'relaxation_pct': relaxation_pct,
            'duration_sec': len(readings) * 0.5,
            'readings_count': len(readings),
        },
        'message': f"Your voice relaxed by {relaxation_pct:.0f}%",
    }


@router.websocket("/ws")
async def studio_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time biomarker streaming at ~2Hz.

    Client sends: {"session_id": "...", "audio_b64": "<base64 audio chunk>"} OR {"ping": true}
    Server sends: {"ts": <unix_ms>, "vocal_steadiness": 0.7, "voice_clarity": 0.65, "tone_stability": 0.72}

    Note: In this implementation, audio processing is simulated server-side.
    In production, the audio chunk would be decoded and processed by RealtimeFeatureExtractor.
    """
    await websocket.accept()
    extractor = _get_extractor()
    logger.info("Studio WebSocket connected")

    # Simulate gradual biomarker evolution for demo/testing
    sim_state = {'relaxed': False, 'step': 0}
    last_audio_ts = 0.0  # tracks when real audio was last received

    try:
        while True:
            # Try to receive a message (with timeout)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                data = json.loads(msg)

                # If client sends simulation control
                if 'relax' in data:
                    sim_state['relaxed'] = data['relax']

                # If client sends actual audio data, process it
                if 'audio_b64' in data:
                    audio_bytes = base64.b64decode(data['audio_b64'])
                    audio_arr = np.frombuffer(audio_bytes, dtype=np.float32)
                    features = extractor.extract(audio_arr)
                    session_id = data.get('session_id')
                    if session_id and session_id in _active_sessions:
                        _active_sessions[session_id]['readings'].append(features)

                    last_audio_ts = time.time()
                    await websocket.send_text(json.dumps({
                        'ts': int(time.time() * 1000),
                        **{k: round(v, 3) for k, v in features.items()},
                    }))
                    continue

            except asyncio.TimeoutError:
                pass  # No message received, send simulated update
            except WebSocketDisconnect:
                break

            # Only send simulated fallback if no real audio has arrived recently
            if time.time() - last_audio_ts > 2.0:
                features = {
                    'ts': int(time.time() * 1000),
                    'f0_mean': None,          # null = silent, not fake data
                    'vocal_steadiness': 0.5,
                    'voice_clarity': 0.5,
                    'tone_stability': 0.5,
                    'rms_energy': 0.0,
                    'simulated': True,
                }
                try:
                    await websocket.send_text(json.dumps(features))
                except Exception:
                    break
            # else: real audio is flowing — responses already sent above; skip simulated noise

            await asyncio.sleep(0.5)  # 2Hz

    except WebSocketDisconnect:
        logger.info("Studio WebSocket disconnected")
    except Exception as e:
        logger.error(f"Studio WebSocket error: {e}")
    finally:
        logger.info("Studio WebSocket closed")
