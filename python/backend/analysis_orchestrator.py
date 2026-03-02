"""
Analysis orchestrator - coordinates the entire analysis pipeline
Runs in dedicated thread: buffer full -> DAM + features -> scores -> DB

Includes:
- Two-tier speech buffer (30s soft / 60s hard trigger)
- VAD confidence tracking and quality gating
- Grace period checking for speech pauses
- Speaker isolation: enrollment gate + RMS filter + segment-level speaker gating
"""
import logging
import threading
import time
from collections import deque
import numpy as np
from datetime import datetime
from typing import Optional
from backend.audio_capture import AudioCapture
from backend.speech_buffer import SpeechBuffer
from backend.acoustic_features import AcousticFeatureExtractor
from backend.score_engine import ScoreEngine
from backend.baseline_calibrator import BaselineCalibrator
from backend.database import Database
import app_config as config

logger = logging.getLogger('attune.orchestrator')


class AnalysisOrchestrator:
    def __init__(self, db: Database, lazy: bool = False):
        """
        Args:
            db: Database instance
            lazy: If True, defer model loading to load_models()
        """
        self.db = db
        self._running_event = threading.Event()   # Thread-safe is_running
        self._paused_event = threading.Event()     # Thread-safe is_paused
        self.meeting_active = False
        # Notification manager — set by main.py after init
        self.notification_manager = None
        # Analytics engine — set by main.py after init
        self.analytics_engine = None

        # Active assessment callback — when set, all audio routes here instead of passive pipeline
        self._active_callback = None

        # Components (fast init)
        self.vad_processor = None
        self.dam_analyzer = None
        self.speaker_verifier = None
        self.speaker_gate = None
        self.audio_capture = None
        self.feature_extractor = None
        self.score_engine = None
        self.calibrator = None

        # Models-ready event: audio callback skips processing until set
        self.models_ready = threading.Event()

        # VAD diagnostic stats (reported every ~10s)
        self._vad_stats = {
            'chunks': 0, 'speech': 0, 'rms_rejected': 0,
            'enrollment_blocked': 0, 'last_report': time.time()
        }
        # One-time enrollment warning (avoid spamming logs)
        self._enrollment_warned = False

        # Bootstrap: auto-enroll one high-confidence segment on first verified reading
        self._bootstrap_done = False

        # Thread lock for meeting state
        self.meeting_lock = threading.Lock()

        # TS-001: Analysis-in-progress guard — Lock instead of bare boolean.
        # acquire(blocking=False) acts as both flag and mutex.
        self._analysis_lock = threading.Lock()
        self._analysis_thread: Optional[threading.Thread] = None
        # EDGE-001: Watchdog for stuck analysis threads
        self._analysis_start_time: Optional[float] = None
        self._ANALYSIS_TIMEOUT = 120  # seconds

        # TS-004: RLock protecting shared mutable state read by frontend
        self._state_lock = threading.RLock()
        # Analysis outcome tracking (protected by _state_lock)
        self._last_analysis_error: Optional[str] = None
        self._last_analysis_time: Optional[str] = None
        self._analysis_success_count: int = 0

        # TS-003: Graceful shutdown event — replaces daemon=True termination
        self._shutdown_event = threading.Event()

        # Mic disconnect tracking (for user notification)
        self._mic_disconnected = False
        # EDGE-003: Audio reconnect debounce
        self._reconnect_cooldown = 2.0  # seconds
        self._last_reconnect_time: float = 0

        # Grace period checker thread (uses _shutdown_event)
        self._grace_thread = None

        # Speech buffer (instant - no model loading)
        self.speech_buffer = SpeechBuffer(
            sample_rate=config.SAMPLE_RATE,
            threshold_sec=config.SPEECH_THRESHOLD_SEC,
            preferred_sec=config.PREFERRED_SPEECH_SEC,
            max_buffer_sec=config.BUFFER_SIZE_SEC,
            grace_period_sec=config.GRACE_PERIOD_SEC,
            on_threshold_callback=self._on_speech_ready
        )

        # Acoustic feature extractor (instant - no model loading)
        self.feature_extractor = AcousticFeatureExtractor(sample_rate=config.SAMPLE_RATE)

        # Baseline calibrator (instant - reads DB)
        self.calibrator = BaselineCalibrator(self.db)

        # Score engine (instant)
        self.score_engine = ScoreEngine(calibrator=self.calibrator)

        # Audio capture (instant - doesn't open stream until start())
        self.audio_capture = AudioCapture(
            sample_rate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            chunk_duration_ms=config.CHUNK_DURATION_MS,
            on_audio_callback=self._on_audio_chunk
        )

        # Wire mic disconnect/reconnect callbacks
        self.audio_capture.set_disconnect_callback(
            on_disconnect=self._on_mic_disconnect,
            on_reconnect=self._on_mic_reconnect,
        )

        if not lazy:
            self.load_models()

        self._initialized = True

    # Thread-safe properties for is_running / is_paused
    @property
    def is_running(self) -> bool:
        return self._running_event.is_set()

    @is_running.setter
    def is_running(self, value: bool):
        if value:
            self._running_event.set()
        else:
            self._running_event.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused_event.is_set()

    @is_paused.setter
    def is_paused(self, value: bool):
        if value:
            self._paused_event.set()
        else:
            self._paused_event.clear()

    def load_models(self):
        """Load slow models (VAD + DAM + Speaker). Call from background thread."""
        from backend.vad_processor import VADProcessor
        from backend.dam_analyzer import DAMAnalyzer
        from backend.speaker_verifier import SpeakerVerifier

        logger.info("Loading VAD model...")
        self.vad_processor = VADProcessor(sample_rate=config.SAMPLE_RATE)

        logger.info("Loading DAM model...")
        for attempt in range(3):
            try:
                self.dam_analyzer = DAMAnalyzer()
                break
            except Exception as e:
                delay = 2 ** attempt  # 1s, 2s, 4s
                if attempt < 2:
                    logger.warning(f"DAM model load attempt {attempt + 1}/3 failed: {e}. Retrying in {delay}s...")
                    import time
                    time.sleep(delay)
                else:
                    logger.warning(f"DAM model failed to load after 3 attempts (non-fatal): {e}")
                    self.dam_analyzer = None

        logger.info("Loading Speaker Verification model...")
        try:
            self.speaker_verifier = SpeakerVerifier(db=self.db)
            self.speaker_verifier.load_model()

            # Initialize SpeakerGate if enrolled
            if self.speaker_verifier.is_enrolled():
                self._init_speaker_gate()
                # Load bootstrap state
                self._bootstrap_done = self.db.get_user_state('speaker_bootstrap_done', '0') == '1'
        except Exception as e:
            logger.warning(f"Speaker verifier failed to load (non-fatal): {e}")
            self.speaker_verifier = None

        self.models_ready.set()
        logger.info("All models loaded and ready")

    def _init_speaker_gate(self):
        """Initialize segment-level speaker gate."""
        if self.speaker_verifier is None:
            return
        from backend.speaker_gate import SpeakerGate
        self.speaker_gate = SpeakerGate(
            speaker_verifier=self.speaker_verifier,
            sample_rate=config.SAMPLE_RATE,
            on_verified_callback=self._on_gate_verified_chunk,
        )
        logger.info("Speaker gate initialized (segment-level verification active)")

    def _on_gate_verified_chunk(self, audio_chunk: np.ndarray, vad_confidence: float):
        """Callback from SpeakerGate — verified chunks pass through to SpeechBuffer."""
        self.speech_buffer.add_speech_chunk(audio_chunk, vad_confidence=vad_confidence)

    def _on_audio_chunk(self, audio_chunk: np.ndarray):
        """
        Callback for each audio chunk from microphone.

        Speaker isolation pipeline:
        1. Skip if paused, not running, or models not loaded
        2. Enrollment gate: block all analysis if enrollment required but not enrolled
        3. VAD: detect speech
        4. RMS energy filter: reject low-energy chunks (TV, distant speakers)
        5. Speaker gate: verify 2s segments via ECAPA before buffering
        6. Speech buffer: accumulate verified speech for DAM analysis
        """
        # Active assessment mode: redirect all audio to the active callback
        if self._active_callback is not None:
            self._active_callback(audio_chunk)
            return

        if self.is_paused or not self.is_running:
            return
        if not self.models_ready.is_set():
            return

        # --- Enrollment gate (Phase 1) ---
        if config.SPEAKER_ENROLLMENT_REQUIRED:
            if not (self.speaker_verifier and self.speaker_verifier.is_enrolled()):
                if not self._enrollment_warned:
                    logger.warning("Voice profile required — analysis blocked until enrollment")
                    self._enrollment_warned = True
                self._vad_stats['enrollment_blocked'] += 1
                return

        # Run VAD to detect speech
        is_speech, confidence = self.vad_processor.is_speech(audio_chunk)

        if is_speech:
            # --- RMS energy filter (Phase 1) ---
            rms = float(np.sqrt(np.mean(audio_chunk ** 2)))
            if rms < config.SPEAKER_RMS_MINIMUM:
                self._vad_stats['rms_rejected'] += 1
                # Still counts as speech for stats, but don't buffer
            elif self.speaker_gate is not None:
                # --- Speaker gate (Phase 2): route through segment verification ---
                self.speaker_gate.add_chunk(audio_chunk, vad_confidence=confidence)
            else:
                # No speaker gate (not enrolled or verifier unavailable) — direct to buffer
                self.speech_buffer.add_speech_chunk(audio_chunk, vad_confidence=confidence)

        # Periodic VAD diagnostics (every ~10s)
        self._vad_stats['chunks'] += 1
        if is_speech:
            self._vad_stats['speech'] += 1
        now = time.time()
        if now - self._vad_stats['last_report'] > 10:
            total = self._vad_stats['chunks']
            speech_count = self._vad_stats['speech']
            rate = speech_count / max(1, total) * 100
            peak = float(np.max(np.abs(audio_chunk)))
            buffered = self.speech_buffer.get_current_duration()
            rms_rej = self._vad_stats['rms_rejected']
            enroll_blk = self._vad_stats['enrollment_blocked']

            extra = ""
            if rms_rej > 0:
                extra += f" | RMS rejected: {rms_rej}"
            if enroll_blk > 0:
                extra += f" | Enrollment blocked: {enroll_blk}"
            if self.speaker_gate:
                gate_stats = self.speaker_gate.get_stats()
                extra += (f" | Gate: {gate_stats['segments_verified']}v/"
                          f"{gate_stats['segments_rejected']}r")

            logger.debug(f"{rate:.0f}% speech ({speech_count}/{total} chunks) | "
                        f"Buffer: {buffered:.1f}s/{config.SPEECH_THRESHOLD_SEC}s | "
                        f"Peak level: {peak:.4f}{extra}")
            self._vad_stats = {
                'chunks': 0, 'speech': 0, 'rms_rejected': 0,
                'enrollment_blocked': 0, 'last_report': now
            }

    def _on_speech_ready(self, speech_audio: np.ndarray, duration_sec: float,
                         vad_confidence: float = 1.0):
        """
        Callback when speech buffer reaches threshold.
        Dispatches analysis to a dedicated thread (non-blocking).

        TS-001: Uses _analysis_lock.acquire(blocking=False) as an atomic
        test-and-set — no bare boolean race between check and assignment.
        """
        if not self.models_ready.is_set():
            return

        if not self._analysis_lock.acquire(blocking=False):
            logger.warning(f"Analysis already in progress, dropping {duration_sec:.1f}s segment")
            return  # Lock already held — analysis in progress

        with self._state_lock:
            self._last_analysis_error = None

        self._analysis_start_time = time.time()  # EDGE-001: watchdog timestamp
        self._analysis_thread = threading.Thread(
            target=self._run_analysis,
            args=(speech_audio, duration_sec, vad_confidence),
            name="analysis-worker"
        )
        self._analysis_thread.start()
        logger.debug("Analysis thread started")

    def _run_analysis(self, speech_audio: np.ndarray, duration_sec: float,
                      vad_confidence: float = 1.0):
        """
        Full analysis pipeline on dedicated thread.
        DAM + features + scores + DB.

        TS-001: Lock is acquired in _on_speech_ready and released in finally here.
        TS-004: Shared outcome state updated under _state_lock.
        """
        try:
            logger.info(f"Starting analysis of {duration_sec:.1f}s speech segment "
                        f"(VAD confidence: {vad_confidence:.2f})")

            # Guard: DAM must be loaded
            if self.dam_analyzer is None:
                with self._state_lock:
                    self._last_analysis_error = "DAM model not loaded — voice analysis unavailable"
                logger.error("DAM model not loaded — voice analysis unavailable")
                return

            # Buffer-level speaker verification (safety net)
            speaker_verified = -1   # -1 = not enrolled (pass-through)
            speaker_similarity = None
            if self.speaker_verifier and self.speaker_verifier.is_enrolled():
                verified, similarity = self.speaker_verifier.verify(speech_audio)
                speaker_verified = 1 if verified else 0
                speaker_similarity = similarity
                if not verified:
                    with self._state_lock:
                        self._last_analysis_error = f"Speaker verification failed (similarity={similarity:.3f})"
                    logger.info(f"Speaker rejected at buffer level "
                                f"(similarity={similarity:.3f}), skipping segment")
                    return
                logger.info(f"Speaker verified (similarity={similarity:.3f})")

                # Bootstrap: auto-enroll this high-confidence segment (one-time)
                if not self._bootstrap_done and similarity >= 0.60:
                    try:
                        self.speaker_verifier.enroll_sample(speech_audio, 'bootstrap')
                        self.speaker_verifier.complete_enrollment()
                        self._bootstrap_done = True
                        self.db.set_user_state('speaker_bootstrap_done', '1')
                        logger.info(f"Bootstrap enrollment complete (similarity={similarity:.3f})")
                    except Exception as be:
                        logger.warning(f"Bootstrap enrollment failed (non-fatal): {be}")

            # Run DAM analysis
            try:
                dam_output = self.dam_analyzer.analyze(speech_audio, sample_rate=config.SAMPLE_RATE)
            except (FileNotFoundError, RuntimeError) as e:
                with self._state_lock:
                    self._last_analysis_error = f"Analysis error: {e}"
                logger.error(f"DAM analysis failed: {e}")
                return

            if dam_output is None:
                with self._state_lock:
                    self._last_analysis_error = "DAM analysis returned no results (check logs)"
                logger.warning("DAM analysis returned None, skipping segment")
                return

            # Extract acoustic features (includes shimmer + voice_breaks)
            acoustic_features = self.feature_extractor.extract(speech_audio)

            # Compute derived scores (includes EMA smoothing)
            scores = self.score_engine.compute_scores(dam_output, acoustic_features)

            # Compute emotional stability from rolling data
            emotional_stability = self._compute_emotional_stability(scores, acoustic_features)
            scores['emotional_stability_score'] = emotional_stability
            scores['emotional_stability_score_raw'] = emotional_stability

            # Determine low-confidence flag (Step 4)
            low_confidence = 1 if vad_confidence < 0.65 else 0
            if low_confidence:
                logger.info(f"Low VAD confidence ({vad_confidence:.2f}) — flagging reading")

            # Combine all data for database
            reading = {
                'timestamp': datetime.now().isoformat(),
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
                **acoustic_features,
                **scores,
                'speech_duration_sec': duration_sec,
                'meeting_detected': 1 if self.meeting_active else 0,
                'vad_confidence': vad_confidence,
                'low_confidence': low_confidence,
                'speaker_verified': speaker_verified,
                'speaker_similarity': speaker_similarity,
            }

            # Insert into database
            reading_id = self.db.insert_reading(reading)

            flags = []
            if dam_output.get('uncertainty_flag'):
                flags.append(dam_output['uncertainty_flag'])
            if dam_output.get('score_inconsistency'):
                flags.append("inconsistent")
            if low_confidence:
                flags.append("low_vad")
            flag_str = f" [{', '.join(flags)}]" if flags else ""

            logger.info(f"Saved reading #{reading_id} - "
                        f"Zone: {scores['zone']}, Mood: {scores['mood_score']:.0f}, "
                        f"Stress: {scores['stress_score']:.0f}{flag_str}")

            # Update baselines (for calibration)
            self.calibrator.update_baselines()

            # Compute daily summary
            self.db.compute_daily_summary()

            # Dispatch notifications (The Pulse)
            if self.notification_manager:
                try:
                    self.notification_manager.on_new_reading(reading)
                except Exception as ne:
                    logger.error(f"Notification error: {ne}")

            # Analytics: track voice reading
            if self.analytics_engine:
                try:
                    today_readings = self.db.get_today_readings()
                    self.analytics_engine.track('voice_reading', {
                        'reading_count_today': len(today_readings) if today_readings else 1,
                        'speech_duration_sec': round(duration_sec, 1),
                        'zone': scores.get('zone', ''),
                    })
                except Exception as ae:
                    logger.debug(f"Analytics tracking error (non-fatal): {ae}")

            # Success — update shared state under lock
            with self._state_lock:
                self._last_analysis_error = None
                self._last_analysis_time = datetime.now().isoformat()
                self._analysis_success_count += 1

        except Exception as e:
            with self._state_lock:
                self._last_analysis_error = f"Analysis error: {str(e)}"
            logger.error(f"Error during analysis: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._analysis_start_time = None  # EDGE-001: clear watchdog
            self._analysis_lock.release()
            logger.debug("Analysis thread finished")

    def _compute_emotional_stability(self, scores: dict, af: dict) -> float:
        """Compute emotional stability from rolling score variance + acoustic CV.
        100 = perfectly stable, 0 = highly volatile.
        With <2 readings: uses acoustic features alone as fallback."""
        try:
            # Get recent readings from last 24 hours (was 2 hours — too narrow for 1/day usage)
            from datetime import datetime, timedelta
            day_ago = (datetime.now() - timedelta(hours=24)).isoformat()
            recent = self.db.get_readings(start_time=day_ago, limit=50)

            # Acoustic CV from current features (always available)
            f0_cv = af.get('f0_std', 0) / max(af.get('f0_mean', 1), 1) * 100
            rms_cv = af.get('rms_sd', 0) / max(af.get('rms_energy', 0.001), 0.001) * 100
            acoustic_cv = min(100.0, float(np.mean([f0_cv, rms_cv])))

            if len(recent) < 2:
                # Acoustic-only fallback: compute stability from voice steadiness alone
                stability = 100.0 - acoustic_cv
                return float(np.clip(stability, 0, 100))

            # Rolling std of 4 core scores (2+ readings available)
            score_keys = ['stress_score', 'wellbeing_score', 'calm_score', 'activation_score']
            stds = []
            for key in score_keys:
                vals = []
                for r in recent:
                    v = r.get(key)
                    if v is None and key == 'wellbeing_score':
                        v = r.get('mood_score')
                    if v is None and key == 'activation_score':
                        v = r.get('energy_score')
                    if v is not None:
                        vals.append(v)
                if len(vals) >= 2:
                    stds.append(float(np.std(vals)))

            if not stds:
                # No valid score pairs — acoustic-only
                stability = 100.0 - acoustic_cv
                return float(np.clip(stability, 0, 100))

            rolling_std = np.mean(stds)
            norm_rolling_std = min(100.0, rolling_std / 15.0 * 100.0)

            stability = 100.0 - (0.60 * norm_rolling_std + 0.40 * acoustic_cv)
            return float(np.clip(stability, 0, 100))
        except Exception as e:
            logger.error(f"Error computing emotional stability: {e}")
            return 75.0

    def _on_mic_disconnect(self, permanent=False):
        """Called when microphone disconnects."""
        if permanent:
            self._mic_disconnected = True
            logger.error("Microphone permanently disconnected — user notification required")
        else:
            logger.warning("Microphone disconnected, attempting reconnection...")

    def _on_mic_reconnect(self):
        """Called when microphone reconnects after disconnect.
        EDGE-003: Debounced to prevent rapid reconnect/disconnect cycles."""
        now = time.time()
        if now - self._last_reconnect_time < self._reconnect_cooldown:
            logger.debug("Reconnect debounced — too soon after last reconnect")
            return
        self._last_reconnect_time = now
        self._mic_disconnected = False
        logger.info("Microphone reconnected successfully")

    def on_enrollment_complete(self):
        """Called after voice enrollment finishes. Initializes speaker gate."""
        self._enrollment_warned = False
        self._init_speaker_gate()
        logger.info("Enrollment complete — speaker gate activated")

    def on_profile_deleted(self):
        """Called after voice profile is deleted. Tears down speaker gate."""
        if self.speaker_gate:
            self.speaker_gate.stop()
            self.speaker_gate = None
        self._enrollment_warned = False
        logger.info("Voice profile deleted — speaker gate deactivated")

    def _grace_check_loop(self):
        """Background thread to check grace period timeout on speech buffer.
        TS-003/TS-007: Uses _shutdown_event.wait() for immediate shutdown response.
        EDGE-001: Also acts as watchdog for stuck analysis threads."""
        logger.debug("Grace-checker thread started")
        while not self._shutdown_event.is_set():
            if self.is_running and not self.is_paused:
                self.speech_buffer.check_grace_timeout()

                # EDGE-001: Watchdog — check for stuck analysis thread
                if (self._analysis_start_time and
                    time.time() - self._analysis_start_time > self._ANALYSIS_TIMEOUT):
                    logger.critical(
                        f"Analysis thread stuck for >{self._ANALYSIS_TIMEOUT}s — force-releasing lock")
                    self._analysis_start_time = None
                    try:
                        self._analysis_lock.release()
                    except RuntimeError:
                        pass  # lock wasn't held

            self._shutdown_event.wait(2.0)  # Wakes immediately on shutdown
        logger.debug("Grace-checker thread stopped")

    def start(self):
        """Start the analysis pipeline"""
        assert self._initialized, "Orchestrator not properly initialized"

        if self.is_running:
            logger.warning("Already running")
            return

        logger.info("Starting analysis pipeline")
        self.is_running = True
        self.is_paused = False

        # TS-003: Clear shutdown event so threads can run
        self._shutdown_event.clear()

        # Start grace period checker thread
        self._grace_thread = threading.Thread(
            target=self._grace_check_loop, daemon=True, name="grace-checker"
        )
        self._grace_thread.start()

        # Start audio capture
        self.audio_capture.start()

        logger.info(f"Pipeline components: buffer={self.speech_buffer is not None}, "
                    f"audio={self.audio_capture is not None}, "
                    f"vad={self.vad_processor is not None}")

        if config.SPEAKER_ENROLLMENT_REQUIRED:
            enrolled = self.speaker_verifier and self.speaker_verifier.is_enrolled()
            if enrolled:
                logger.info("Analysis pipeline started (voice profile active)")
            else:
                logger.info("Analysis pipeline started (awaiting voice enrollment)")
        else:
            logger.info("Analysis pipeline started")

    def stop(self):
        """Stop the analysis pipeline.
        TS-003: Signals shutdown event and joins threads with timeout."""
        if not self.is_running:
            return

        logger.info("Stopping analysis pipeline")
        self.is_running = False

        # TS-003: Signal all threads to stop
        self._shutdown_event.set()

        # Join grace-checker thread
        if self._grace_thread and self._grace_thread.is_alive():
            self._grace_thread.join(timeout=5)
            if self._grace_thread.is_alive():
                logger.warning("Grace-checker thread did not stop within timeout")

        # Join analysis thread if running
        if self._analysis_thread and self._analysis_thread.is_alive():
            self._analysis_thread.join(timeout=10)
            if self._analysis_thread.is_alive():
                logger.warning("Analysis thread did not stop within timeout")

        # Stop speaker gate
        if self.speaker_gate:
            self.speaker_gate.stop()

        # Stop audio capture
        if self.audio_capture:
            self.audio_capture.stop()

        # Clear speech buffer
        self.speech_buffer.clear()

        logger.info("Analysis pipeline stopped")

    def pause(self):
        """Pause analysis (stop accumulating speech)"""
        self.is_paused = True
        logger.info("Analysis paused")

    def resume(self):
        """Resume analysis"""
        self.is_paused = False
        logger.info("Analysis resumed")

    def set_active_mode(self, callback=None):
        """Set or clear active assessment mode.
        When callback is set, all audio chunks route to it instead of the passive pipeline.
        When cleared (None), passive pipeline resumes."""
        if callback is not None:
            self._active_callback = callback
            self.is_paused = True  # Pause passive pipeline
            self.speech_buffer.clear()
            logger.info("Active assessment mode enabled — passive pipeline paused")
        else:
            self._active_callback = None
            self.is_paused = False  # Resume passive pipeline
            logger.info("Active assessment mode disabled — passive pipeline resumed")

    def set_meeting_active(self, active: bool):
        """Set whether a meeting is currently active"""
        with self.meeting_lock:
            self.meeting_active = active
            status = "started" if active else "ended"
            logger.info(f"Meeting {status}")

    def get_status(self) -> dict:
        """Get current orchestrator status.
        TS-001/TS-004: Reads analysis state under locks for thread safety."""
        enrolled = bool(self.speaker_verifier and self.speaker_verifier.is_enrolled())
        gate_stats = self.speaker_gate.get_stats() if self.speaker_gate else None
        if gate_stats and self.speaker_verifier:
            gate_stats['adaptive_threshold'] = round(self.speaker_verifier.threshold, 3)

        # TS-001: Derive is_analyzing from lock state (locked = analysis in progress)
        is_analyzing = self._analysis_lock.locked()

        with self._state_lock:
            last_error = self._last_analysis_error
            success_count = self._analysis_success_count

        return {
            'is_running': self.is_running,
            'is_paused': self.is_paused,
            'meeting_active': self.meeting_active,
            'buffered_speech_sec': self.speech_buffer.get_current_duration(),
            'buffered_vad_confidence': self.speech_buffer.get_mean_confidence(),
            'calibration_status': self.calibrator.get_calibration_status(),
            'is_analyzing': is_analyzing,
            'last_analysis_error': last_error,
            'analysis_success_count': success_count,
            'speaker_enrolled': enrolled,
            'enrollment_required': config.SPEAKER_ENROLLMENT_REQUIRED,
            'speaker_gate_stats': gate_stats,
            'mic_disconnected': self._mic_disconnected,
        }
