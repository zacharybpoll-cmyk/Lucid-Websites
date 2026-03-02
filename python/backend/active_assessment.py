"""
Active Assessment Runner — manages on-demand Voice Scan recording sessions.

No speaker gate (user is intentionally recording). Audio flows:
  mic → VAD → speech buffer → DAM analysis → results

Uses orchestrator's set_active_mode() to redirect the shared mic stream.
"""
import logging
import threading
import time
import numpy as np
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any

from backend.database import Database
from backend.analysis_orchestrator import AnalysisOrchestrator
import app_config as config

logger = logging.getLogger('attune.active_assessment')


class ActiveAssessmentRunner:
    def __init__(self, db: Database, orchestrator: AnalysisOrchestrator):
        self.db = db
        self.orchestrator = orchestrator

        # Session state
        self._active = False
        self._lock = threading.Lock()

        # Audio accumulation
        self._speech_chunks: list = []
        self._total_speech_sec: float = 0.0
        self._recording_start: Optional[float] = None
        self._total_recording_sec: float = 0.0

        # RMS levels for visualization (last 60 values)
        self._rms_history: deque = deque(maxlen=60)
        self._speech_detected: bool = False

        # Prompt used for this session
        self._prompt_text: Optional[str] = None

        # Analysis result (set after stop)
        self._last_result: Optional[Dict[str, Any]] = None

    @property
    def is_active(self) -> bool:
        return self._active

    def start_session(self, prompt_text: str = '') -> Dict[str, Any]:
        """Start a voice scan recording session."""
        with self._lock:
            if self._active:
                return {'error': 'Session already active'}

            if not self.orchestrator.models_ready.is_set():
                return {'error': 'Models not loaded yet — please wait'}

            # Reset state
            self._speech_chunks = []
            self._total_speech_sec = 0.0
            self._recording_start = time.time()
            self._total_recording_sec = 0.0
            self._rms_history.clear()
            self._speech_detected = False
            self._prompt_text = prompt_text
            self._last_result = None
            self._active = True

            # Redirect orchestrator audio to our callback
            self.orchestrator.set_active_mode(callback=self._on_audio_chunk)

            logger.info("Voice scan session started")
            return {'status': 'recording', 'prompt_text': prompt_text}

    def _on_audio_chunk(self, audio_chunk: np.ndarray):
        """Process each audio chunk — VAD only, no speaker gate."""
        if not self._active:
            return

        # Check max recording time — auto-stop cleanly
        elapsed = time.time() - self._recording_start
        if elapsed > config.ACTIVE_MAX_RECORDING_SEC:
            if self._active:
                logger.info("Voice scan hit max recording time, auto-stopping")
                self._active = False
                self.orchestrator.set_active_mode(callback=None)
            return

        # Compute RMS for visualization
        rms = float(np.sqrt(np.mean(audio_chunk ** 2)))
        self._rms_history.append(rms)

        # Run VAD (reuse orchestrator's loaded model)
        vad = self.orchestrator.vad_processor
        if vad is None:
            return

        is_speech, confidence = vad.is_speech(audio_chunk)

        if is_speech:
            # No RMS filter for active mode — user is intentionally speaking
            self._speech_detected = True
            self._speech_chunks.append(audio_chunk.copy())
            chunk_duration = len(audio_chunk) / config.SAMPLE_RATE
            self._total_speech_sec += chunk_duration

    def get_session_status(self) -> Dict[str, Any]:
        """Return current session status for frontend polling."""
        if not self._active:
            return {
                'active': False,
                'speech_duration_sec': 0,
                'total_recording_sec': 0,
                'rms_levels': [],
                'speech_detected': False,
                'ready_for_analysis': False,
            }

        elapsed = time.time() - self._recording_start if self._recording_start else 0
        return {
            'active': True,
            'speech_duration_sec': round(self._total_speech_sec, 1),
            'total_recording_sec': round(elapsed, 1),
            'rms_levels': list(self._rms_history),
            'speech_detected': self._speech_detected,
            'ready_for_analysis': self._total_speech_sec >= config.ACTIVE_MIN_SPEECH_SEC,
            'max_recording_sec': config.ACTIVE_MAX_RECORDING_SEC,
            'min_speech_sec': config.ACTIVE_MIN_SPEECH_SEC,
        }

    def stop_session(self) -> Dict[str, Any]:
        """Stop recording, run analysis, store result, resume passive pipeline."""
        with self._lock:
            if not self._active:
                return {'error': 'No active session'}

            self._active = False
            recording_duration = time.time() - self._recording_start if self._recording_start else 0

            # Check minimum speech
            if self._total_speech_sec < config.ACTIVE_MIN_SPEECH_SEC:
                self.orchestrator.set_active_mode(callback=None)
                return {
                    'error': f'Not enough speech detected ({self._total_speech_sec:.1f}s). '
                             f'Need at least {config.ACTIVE_MIN_SPEECH_SEC}s.',
                    'speech_duration_sec': self._total_speech_sec,
                }

            # Concatenate speech chunks
            if not self._speech_chunks:
                self.orchestrator.set_active_mode(callback=None)
                return {'error': 'No speech captured'}

            speech_audio = np.concatenate(self._speech_chunks)
            speech_duration = self._total_speech_sec

            logger.info(f"Voice scan: {speech_duration:.1f}s speech in {recording_duration:.1f}s recording")

        # Run analysis (outside lock to avoid blocking)
        try:
            result = self._run_analysis(speech_audio, speech_duration, recording_duration)
        except Exception as e:
            logger.error(f"Voice scan analysis failed: {e}")
            result = {'error': f'Analysis failed: {str(e)}'}
        finally:
            # Always resume passive pipeline
            self.orchestrator.set_active_mode(callback=None)

        self._last_result = result
        return result

    def _run_analysis(self, speech_audio: np.ndarray, speech_duration: float,
                      recording_duration: float) -> Dict[str, Any]:
        """Run DAM + score engine on the captured speech (no EMA smoothing)."""
        dam = self.orchestrator.dam_analyzer
        if dam is None:
            raise RuntimeError("DAM model not loaded")

        # Run DAM
        dam_output = dam.analyze(speech_audio, sample_rate=config.SAMPLE_RATE)
        if dam_output is None:
            raise RuntimeError("DAM analysis returned no results")

        # Extract acoustic features
        acoustic_features = self.orchestrator.feature_extractor.extract(speech_audio)

        # Compute scores WITHOUT EMA smoothing (fresh computation for voice scan)
        from backend.score_engine import ScoreEngine
        fresh_engine = ScoreEngine(calibrator=self.orchestrator.calibrator)
        scores = fresh_engine.compute_scores(dam_output, acoustic_features)

        # Build result
        result = {
            'timestamp': datetime.now().isoformat(),
            'speech_duration_sec': round(speech_duration, 1),
            'recording_duration_sec': round(recording_duration, 1),
            # DAM outputs
            'depression_raw': dam_output['depression_raw'],
            'anxiety_raw': dam_output['anxiety_raw'],
            'depression_mapped': dam_output.get('depression_mapped'),
            'anxiety_mapped': dam_output.get('anxiety_mapped'),
            'depression_quantized': dam_output['depression_quantized'],
            'anxiety_quantized': dam_output['anxiety_quantized'],
            'depression_ci_lower': dam_output.get('depression_ci_lower'),
            'depression_ci_upper': dam_output.get('depression_ci_upper'),
            'anxiety_ci_lower': dam_output.get('anxiety_ci_lower'),
            'anxiety_ci_upper': dam_output.get('anxiety_ci_upper'),
            'uncertainty_flag': dam_output.get('uncertainty_flag'),
            'score_inconsistency': dam_output.get('score_inconsistency', 0),
            # Composite scores
            'stress_score': scores.get('stress_score'),
            'mood_score': scores.get('mood_score'),
            'energy_score': scores.get('energy_score'),
            'calm_score': scores.get('calm_score'),
            'wellbeing_score': scores.get('wellbeing_score'),
            'activation_score': scores.get('activation_score'),
            'depression_risk_score': scores.get('depression_risk_score'),
            'anxiety_risk_score': scores.get('anxiety_risk_score'),
            'emotional_stability_score': scores.get('emotional_stability_score'),
            'zone': scores.get('zone'),
            'prompt_text': self._prompt_text,
        }

        # Store in database
        assessment_id = self.db.insert_active_assessment(result)
        result['id'] = assessment_id

        logger.info(f"Voice scan #{assessment_id} complete — "
                    f"PHQ-9: {result['depression_mapped']:.1f}, GAD-7: {result['anxiety_mapped']:.1f}, "
                    f"Zone: {result['zone']}")

        return result

    def cancel_session(self) -> Dict[str, Any]:
        """Cancel the current session without analysis."""
        with self._lock:
            was_active = self._active
            self._active = False
            self._speech_chunks = []
            self._rms_history.clear()

        if was_active:
            self.orchestrator.set_active_mode(callback=None)
            logger.info("Voice scan session cancelled")

        return {'status': 'cancelled'}
