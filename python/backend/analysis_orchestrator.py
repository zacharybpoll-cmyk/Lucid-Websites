"""
Analysis orchestrator - coordinates the entire analysis pipeline
Runs in dedicated thread: buffer full -> DAM + features -> scores -> DB

Includes:
- Two-tier speech buffer (30s soft / 60s hard trigger)
- VAD confidence tracking and quality gating
- Grace period checking for speech pauses
- Speaker isolation: enrollment gate + RMS filter + segment-level speaker gating
"""
import threading
import time
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


class AnalysisOrchestrator:
    def __init__(self, db: Database, lazy: bool = False):
        """
        Args:
            db: Database instance
            lazy: If True, defer model loading to load_models()
        """
        self.db = db
        self.is_running = False
        self.is_paused = False
        self.meeting_active = False
        # Notification manager — set by main.py after init
        self.notification_manager = None

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

        # Thread lock for meeting state
        self.meeting_lock = threading.Lock()

        # Grace period checker thread
        self._grace_thread = None
        self._grace_stop = threading.Event()

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

        if not lazy:
            self.load_models()

    def load_models(self):
        """Load slow models (VAD + DAM + Speaker). Call from background thread."""
        from backend.vad_processor import VADProcessor
        from backend.dam_analyzer import DAMAnalyzer
        from backend.speaker_verifier import SpeakerVerifier

        print("[Orchestrator] Loading VAD model...")
        self.vad_processor = VADProcessor(sample_rate=config.SAMPLE_RATE)

        print("[Orchestrator] Loading DAM model...")
        self.dam_analyzer = DAMAnalyzer()

        print("[Orchestrator] Loading Speaker Verification model...")
        try:
            self.speaker_verifier = SpeakerVerifier(db=self.db)
            self.speaker_verifier.load_model()

            # Initialize SpeakerGate if enrolled
            if self.speaker_verifier.is_enrolled():
                self._init_speaker_gate()
        except Exception as e:
            print(f"[Orchestrator] Speaker verifier failed to load (non-fatal): {e}")
            self.speaker_verifier = None

        self.models_ready.set()
        print("[Orchestrator] All models loaded and ready")

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
        print("[Orchestrator] Speaker gate initialized (segment-level verification active)")

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
        if self.is_paused or not self.is_running:
            return
        if not self.models_ready.is_set():
            return

        # --- Enrollment gate (Phase 1) ---
        if config.SPEAKER_ENROLLMENT_REQUIRED:
            if not (self.speaker_verifier and self.speaker_verifier.is_enrolled()):
                if not self._enrollment_warned:
                    print("[Orchestrator] Voice profile required — analysis blocked until enrollment")
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

            print(f"[VAD Stats] {rate:.0f}% speech ({speech_count}/{total} chunks) | "
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
        Triggers full analysis: DAM + features + scores.

        Buffer-level speaker verification acts as a safety net
        (segments are already pre-verified by SpeakerGate).
        """
        if not self.models_ready.is_set():
            return

        print(f"[Orchestrator] Starting analysis of {duration_sec:.1f}s speech segment "
              f"(VAD confidence: {vad_confidence:.2f})")

        # Buffer-level speaker verification (safety net)
        speaker_verified = -1   # -1 = not enrolled (pass-through)
        speaker_similarity = None
        if self.speaker_verifier and self.speaker_verifier.is_enrolled():
            verified, similarity = self.speaker_verifier.verify(speech_audio)
            speaker_verified = 1 if verified else 0
            speaker_similarity = similarity
            if not verified:
                print(f"[Orchestrator] Speaker rejected at buffer level "
                      f"(similarity={similarity:.3f}), skipping segment")
                return
            print(f"[Orchestrator] Speaker verified (similarity={similarity:.3f})")

        try:
            # Run DAM analysis
            dam_output = self.dam_analyzer.analyze(speech_audio, sample_rate=config.SAMPLE_RATE)

            if dam_output is None:
                print("[Orchestrator] DAM analysis returned None (error), skipping this segment")
                return

            # Extract acoustic features (includes shimmer + voice_breaks)
            acoustic_features = self.feature_extractor.extract(speech_audio)

            # Compute derived scores (includes EMA smoothing + shimmer weight)
            scores = self.score_engine.compute_scores(dam_output, acoustic_features)

            # Determine low-confidence flag (Step 4)
            low_confidence = 1 if vad_confidence < 0.65 else 0
            if low_confidence:
                print(f"[Orchestrator] Low VAD confidence ({vad_confidence:.2f}) — flagging reading")

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

            print(f"[Orchestrator] Saved reading #{reading_id} - "
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
                    print(f"[Orchestrator] Notification error: {ne}")

        except Exception as e:
            print(f"[Orchestrator] Error during analysis: {e}")
            import traceback
            traceback.print_exc()

    def on_enrollment_complete(self):
        """Called after voice enrollment finishes. Initializes speaker gate."""
        self._enrollment_warned = False
        self._init_speaker_gate()
        print("[Orchestrator] Enrollment complete — speaker gate activated")

    def on_profile_deleted(self):
        """Called after voice profile is deleted. Tears down speaker gate."""
        if self.speaker_gate:
            self.speaker_gate.stop()
            self.speaker_gate = None
        self._enrollment_warned = False
        print("[Orchestrator] Voice profile deleted — speaker gate deactivated")

    def _grace_check_loop(self):
        """Background thread to check grace period timeout on speech buffer."""
        while not self._grace_stop.is_set():
            if self.is_running and not self.is_paused:
                self.speech_buffer.check_grace_timeout()
            self._grace_stop.wait(2.0)  # Check every 2 seconds

    def start(self):
        """Start the analysis pipeline"""
        if self.is_running:
            print("[Orchestrator] Already running")
            return

        print("[Orchestrator] Starting analysis pipeline")
        self.is_running = True
        self.is_paused = False

        # Start grace period checker thread
        self._grace_stop.clear()
        self._grace_thread = threading.Thread(
            target=self._grace_check_loop, daemon=True, name="grace-checker"
        )
        self._grace_thread.start()

        # Start audio capture
        self.audio_capture.start()

        if config.SPEAKER_ENROLLMENT_REQUIRED:
            enrolled = self.speaker_verifier and self.speaker_verifier.is_enrolled()
            if enrolled:
                print("[Orchestrator] Analysis pipeline started (voice profile active)")
            else:
                print("[Orchestrator] Analysis pipeline started (awaiting voice enrollment)")
        else:
            print("[Orchestrator] Analysis pipeline started")

    def stop(self):
        """Stop the analysis pipeline"""
        if not self.is_running:
            return

        print("[Orchestrator] Stopping analysis pipeline")
        self.is_running = False

        # Stop grace period checker
        self._grace_stop.set()

        # Stop speaker gate
        if self.speaker_gate:
            self.speaker_gate.stop()

        # Stop audio capture
        if self.audio_capture:
            self.audio_capture.stop()

        # Clear speech buffer
        self.speech_buffer.clear()

        print("[Orchestrator] Analysis pipeline stopped")

    def pause(self):
        """Pause analysis (stop accumulating speech)"""
        self.is_paused = True
        print("[Orchestrator] Analysis paused")

    def resume(self):
        """Resume analysis"""
        self.is_paused = False
        print("[Orchestrator] Analysis resumed")

    def set_meeting_active(self, active: bool):
        """Set whether a meeting is currently active"""
        with self.meeting_lock:
            self.meeting_active = active
            status = "started" if active else "ended"
            print(f"[Orchestrator] Meeting {status}")

    def get_status(self) -> dict:
        """Get current orchestrator status"""
        enrolled = bool(self.speaker_verifier and self.speaker_verifier.is_enrolled())
        gate_stats = self.speaker_gate.get_stats() if self.speaker_gate else None

        return {
            'is_running': self.is_running,
            'is_paused': self.is_paused,
            'meeting_active': self.meeting_active,
            'buffered_speech_sec': self.speech_buffer.get_current_duration(),
            'buffered_vad_confidence': self.speech_buffer.get_mean_confidence(),
            'calibration_status': self.calibrator.get_calibration_status(),
            'speaker_enrolled': enrolled,
            'enrollment_required': config.SPEAKER_ENROLLMENT_REQUIRED,
            'speaker_gate_stats': gate_stats,
        }
