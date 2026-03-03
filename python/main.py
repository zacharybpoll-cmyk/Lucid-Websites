#!/usr/bin/env python3
"""
Lucid - Main Entry Point
Browser-based: starts uvicorn, loads models in background, opens browser automatically.
Includes The Beacon (dynamic menubar icon) and The Pulse (notification engine).
"""
# Model cache setup — MUST happen before any torch/HuggingFace imports
from model_setup import setup_model_cache
setup_model_cache()

import os
import sys
import signal
import socket
import threading
import time
import argparse
import gc
import traceback
import webbrowser
import logging
from datetime import datetime
from pathlib import Path
import psutil
from backend.logging_config import setup_logging
from backend.database import Database
from backend.analysis_orchestrator import AnalysisOrchestrator
from backend.meeting_detector import MeetingDetector
from backend.insight_engine import InsightEngine
from backend.notifications import NotificationManager
from backend.active_assessment import ActiveAssessmentRunner
import app_config as config

# Import API dependencies and routes
import api.dependencies as deps
import api.routes as routes
import uvicorn

logger = logging.getLogger('lucid.main')


# ============ Crash Reporting ============

def _sanitize_crash_log(text: str) -> str:
    """Redact sensitive data from crash log entries.
    NOTE: Identical sanitization rules exist in main.js:sanitizeCrashLog()
    If you change these patterns, update both locations."""
    import re
    # Redact embedding vectors (arrays of 10+ floats)
    text = re.sub(r'\[(-?\d+\.\d+,\s*){9,}-?\d+\.\d+\]', '[<embedding redacted>]', text)
    # Replace home directory paths with ~
    home = os.path.expanduser('~')
    text = text.replace(home, '~')
    # Redact long base64 strings (40+ chars)
    text = re.sub(r'[A-Za-z0-9+/]{40,}={0,2}', '<base64 redacted>', text)
    return text


def _setup_crash_reporting():
    crash_log = Path(os.environ.get('LUCID_DATA_DIR', '.')) / 'crash_log.txt'

    # Truncate crash log if >1MB (keep last 500KB)
    try:
        if crash_log.exists() and crash_log.stat().st_size > 1_048_576:
            data = crash_log.read_bytes()
            crash_log.write_bytes(data[-512_000:])
            logging.getLogger('lucid.main').info("Truncated crash log (was >1MB)")
    except Exception as e:
        pass  # Crash log truncation is best-effort

    def excepthook(exc_type, exc_value, exc_tb):
        timestamp = datetime.now().isoformat()
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        tb_str = _sanitize_crash_log(tb_str)
        entry = f"[{timestamp}] [python-uncaught] {tb_str}\n"
        try:
            with open(crash_log, 'a') as f:
                f.write(entry)
        except Exception:
            pass  # Can't log crash-log write failures (circular)
        # Call the default hook too
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook


# ============ Memory Monitoring ============

def _start_memory_monitor(interval_sec=300, orchestrator=None, insight_engine=None):
    """Check memory usage every 5 minutes. Active throttling at >2GB."""
    def monitor():
        while True:
            time.sleep(interval_sec)
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)

            if mem_mb > 2560:
                # Critical: >2.5GB — pause analysis for 60s after GC
                logger.critical(f"Memory critical: {mem_mb:.0f}MB (>2.5GB) — forcing GC and pausing analysis")
                gc.collect()
                if insight_engine and hasattr(insight_engine, '_cache'):
                    try:
                        insight_engine._cache.clear()
                    except Exception as e:
                        pass  # Cache clear is best-effort
                if orchestrator and orchestrator.is_running:
                    orchestrator.pause()
                    time.sleep(60)
                    orchestrator.resume()
                    logger.info("Analysis resumed after memory cooldown")
            elif mem_mb > 2048:
                # Warning: >2GB — run GC and clear caches
                logger.warning(f"Memory usage high: {mem_mb:.0f}MB (>2GB) — running GC")
                gc.collect()
                if insight_engine and hasattr(insight_engine, '_cache'):
                    try:
                        insight_engine._cache.clear()
                    except Exception as e:
                        pass  # Cache clear is best-effort
            elif mem_mb > 1024:
                logger.info(f"Memory usage: {mem_mb:.0f}MB")

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()



def _wait_for_server_socket(host, port, timeout=10.0):
    """Poll until the server is accepting connections."""
    deadline = time.monotonic() + timeout
    delay = 0.2
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(delay)
            delay = min(delay * 1.5, 1.0)
    return False


class Lucid:
    def __init__(self, electron_mode=False):
        self.electron_mode = electron_mode
        self.db = None
        self.orchestrator = None
        self.meeting_detector = None
        self.insight_engine = None
        self.notification_manager = None
        self.active_runner = None
        self.analytics_engine = None
        self.server = None
        self._shutdown = threading.Event()

    def run(self):
        logger.info("=" * 60)
        logger.info("Lucid — Clarity through voice.")
        logger.info("=" * 60)

        # --- Fast init (< 1s) ---
        logger.info("Initializing database...")
        self.db = Database(config.DB_PATH)
        self.db.check_and_repair()       # EDGE-002: integrity check on startup
        self.db.prune_old_readings(90)   # MEM-004: retention policy
        logger.info(f"Database ready at {config.DB_PATH}")

        # Create orchestrator with lazy model loading (fast)
        logger.info("Creating orchestrator (models will load in background)...")
        self.orchestrator = AnalysisOrchestrator(self.db, lazy=True)

        # Create meeting detector
        def on_meeting_change(active):
            if self.orchestrator:
                self.orchestrator.set_meeting_active(active)
        self.meeting_detector = MeetingDetector(on_meeting_change=on_meeting_change)

        # Create insight engine
        logger.info("Initializing insight engine...")
        self.insight_engine = InsightEngine()

        # Create notification manager (The Pulse)
        logger.info("Initializing notification engine...")
        self.notification_manager = NotificationManager(self.db)
        self.notification_manager.schedule_curtain_call()

        # Wire notification manager into orchestrator
        self.orchestrator.notification_manager = self.notification_manager

        # Wire analytics engine into orchestrator (set after analytics init below)

        # Create active assessment runner (Voice Scan)
        self.active_runner = ActiveAssessmentRunner(self.db, self.orchestrator)

        # Initialize analytics engine
        if config.ANALYTICS_ENABLED and config.SUPABASE_URL and config.SUPABASE_KEY:
            from backend.analytics import AnalyticsEngine
            try:
                app_version = os.environ.get('npm_package_version', '1.0.0')
                self.analytics_engine = AnalyticsEngine(
                    supabase_url=config.SUPABASE_URL,
                    supabase_key=config.SUPABASE_KEY,
                    data_dir=config.DATA_DIR,
                    app_version=app_version,
                    flush_interval=config.ANALYTICS_FLUSH_INTERVAL,
                    db=self.db,
                )
                self.analytics_engine.start()
                logger.info("Analytics engine initialized")
            except Exception as e:
                logger.warning(f"Analytics engine failed to start (non-fatal): {e}")
                self.analytics_engine = None
        else:
            logger.info("Analytics disabled (no Supabase credentials)")

        # Wire analytics engine into orchestrator
        if self.analytics_engine:
            self.orchestrator.analytics_engine = self.analytics_engine

        # Wire up API dependencies
        deps.db = self.db
        deps.orchestrator = self.orchestrator
        deps.meeting_detector = self.meeting_detector
        deps.insight_engine = self.insight_engine
        deps.notification_manager = self.notification_manager
        deps.active_runner = self.active_runner
        deps.analytics_engine = self.analytics_engine

        # Wire up legacy route globals (routes.py endpoints use module-level vars)
        routes.db = self.db
        routes.orchestrator = self.orchestrator
        routes.meeting_detector = self.meeting_detector
        routes.insight_engine = self.insight_engine
        routes.notification_manager = self.notification_manager
        routes.active_runner = self.active_runner

        # --- Start uvicorn in a daemon thread ---
        logger.info(f"Starting server on http://{config.API_HOST}:{config.API_PORT}")
        uv_config = uvicorn.Config(
            routes.app,
            host=config.API_HOST,
            port=config.API_PORT,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(uv_config)
        # Prevent uvicorn from installing its own signal handlers (we handle Ctrl+C)
        self.server.install_signal_handlers = lambda: None
        server_thread = threading.Thread(target=self.server.run, daemon=True)
        server_thread.start()

        # Wait until uvicorn is accepting connections (or thread dies)
        if not _wait_for_server_socket(config.API_HOST, config.API_PORT):
            pass  # Fall through to the thread-alive check below
        if not server_thread.is_alive():
            logger.error(f"Server failed to start. Port {config.API_PORT} is likely in use.")
            logger.error(f"Run: lsof -ti :{config.API_PORT} | xargs kill -9")
            sys.exit(1)

        # --- Start memory monitor (MEM-005: 60s interval for faster response) ---
        _start_memory_monitor(interval_sec=60, orchestrator=self.orchestrator, insight_engine=self.insight_engine)

        # --- Start periodic database backup (every 6 hours) ---
        def _periodic_backup():
            while not self._shutdown.is_set():
                self._shutdown.wait(6 * 3600)  # 6 hours
                if self._shutdown.is_set():
                    break
                if self.db:
                    self.db.backup()
        threading.Thread(target=_periodic_backup, daemon=True).start()

        # --- Load models in background thread ---
        def _load_models():
            try:
                self.orchestrator.load_models()
                logger.info("Models loaded - starting analysis pipeline")
                self.orchestrator.start()
                self.meeting_detector.start()
            except Exception as e:
                logger.error(f"Model loading failed: {e}")
                import traceback
                traceback.print_exc()

        model_thread = threading.Thread(target=_load_models, daemon=True)
        model_thread.start()

        # --- Wait for server to respond, then open browser (unless --electron) ---
        if not self.electron_mode:
            url = f"http://{config.API_HOST}:{config.API_PORT}/static/index.html"
            self._wait_for_server(url=f"http://{config.API_HOST}:{config.API_PORT}/")
            logger.info(f"Opening browser at {url}")
            webbrowser.open(url)

        # --- Block until signal ---
        mode_label = "Electron" if self.electron_mode else "Ctrl+C"
        logger.info(f"Running ({mode_label} mode). Waiting for shutdown signal.")
        try:
            self._shutdown.wait()
        except KeyboardInterrupt:
            pass

        self._cleanup()

    def _wait_for_server(self, url, timeout=15):
        """Poll the server until it responds."""
        import urllib.request
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(url, timeout=2)
                return
            except Exception:
                time.sleep(0.3)  # Expected during startup polling
        logger.warning("Server did not respond within timeout, opening browser anyway")

    def _cleanup(self):
        logger.info("Shutting down...")
        if self.analytics_engine:
            self.analytics_engine.stop()
        if self.notification_manager:
            self.notification_manager.stop()
        if self.orchestrator:
            self.orchestrator.stop()
        if self.meeting_detector:
            self.meeting_detector.stop()
        if self.server:
            self.server.should_exit = True
        if self.db:
            self.db.close()
        logger.info("Goodbye.")

def main():
    setup_logging(log_dir=str(config.DATA_DIR))
    _setup_crash_reporting()

    parser = argparse.ArgumentParser(description='Lucid — Voice Wellness Monitor')
    parser.add_argument('--electron', action='store_true', help='Run in Electron mode (no browser open)')
    args = parser.parse_args()

    lucid_app = Lucid(electron_mode=args.electron)

    # Handle Ctrl+C and SIGTERM gracefully
    def _sig_handler(sig, frame):
        lucid_app._shutdown.set()
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    lucid_app.run()


if __name__ == '__main__':
    main()
