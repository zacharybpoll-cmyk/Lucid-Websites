#!/usr/bin/env python3
"""
Attune - Main Entry Point
Browser-based: starts uvicorn, loads models in background, opens browser automatically.
Includes The Beacon (dynamic menubar icon) and The Pulse (notification engine).
"""
import os
import sys
import signal
import socket
import threading
import time
import argparse
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
import app_config as config

# Import API routes and set global references
import api.routes as routes
import uvicorn

logger = logging.getLogger('attune.main')


# ============ Crash Reporting ============

def _setup_crash_reporting():
    crash_log = Path(os.environ.get('ATTUNE_DATA_DIR', '.')) / 'crash_log.txt'

    def excepthook(exc_type, exc_value, exc_tb):
        timestamp = datetime.now().isoformat()
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        entry = f"[{timestamp}] [python-uncaught] {tb_str}\n"
        try:
            with open(crash_log, 'a') as f:
                f.write(entry)
        except Exception:
            pass
        # Call the default hook too
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook


# ============ Memory Monitoring ============

def _start_memory_monitor(interval_sec=300):
    """Check memory usage every 5 minutes, warn if >2GB."""
    def monitor():
        while True:
            time.sleep(interval_sec)
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            if mem_mb > 2048:
                logger.warning(f"Memory usage high: {mem_mb:.0f}MB (>2GB)")
            elif mem_mb > 1024:
                logger.info(f"Memory usage: {mem_mb:.0f}MB")

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()


# ============ The Beacon — Dynamic Menubar Icon ============

def _create_beacon_icons():
    """Generate colored dot icons for menubar using PIL."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("PIL not available, menubar icons disabled")
        return {}

    icons = {}
    colors = {
        'calm': '#5a9a6e',
        'steady': '#b5a84a',
        'tense': '#d4943a',
        'stressed': '#c4584c',
        'idle': '#888888',
    }

    for zone, color in colors.items():
        img = Image.new('RGBA', (22, 22), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Draw filled circle with slight border
        draw.ellipse([3, 3, 19, 19], fill=color, outline=color)
        # Inner highlight for depth
        draw.ellipse([6, 6, 16, 16], fill=color)
        icons[zone] = img

    return icons


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


class Attune:
    def __init__(self, electron_mode=False):
        self.electron_mode = electron_mode
        self.db = None
        self.orchestrator = None
        self.meeting_detector = None
        self.insight_engine = None
        self.notification_manager = None
        self.server = None
        self._shutdown = threading.Event()
        # Beacon state
        self._beacon_icons = {}
        self._beacon_current_zone = 'idle'

    def run(self):
        logger.info("=" * 60)
        logger.info("Attune — Attuned to you.")
        logger.info("=" * 60)

        # --- Fast init (< 1s) ---
        logger.info("Initializing database...")
        self.db = Database(config.DB_PATH)
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

        # Initialize Beacon icons
        self._beacon_icons = _create_beacon_icons()

        # Wire notification manager into orchestrator
        self.orchestrator.notification_manager = self.notification_manager

        # Wire up API routes
        routes.db = self.db
        routes.orchestrator = self.orchestrator
        routes.meeting_detector = self.meeting_detector
        routes.insight_engine = self.insight_engine
        routes.notification_manager = self.notification_manager

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

        # --- Start memory monitor ---
        _start_memory_monitor()

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
                time.sleep(0.3)
        logger.warning("Server did not respond within timeout, opening browser anyway")

    def _cleanup(self):
        logger.info("Shutting down...")
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

    def update_beacon(self, zone: str):
        """Update the menubar beacon icon color based on current zone."""
        if zone == self._beacon_current_zone:
            return
        self._beacon_current_zone = zone
        # Beacon icons are informational only (no pystray in browser mode)
        # The actual icon state is tracked and available via /api/status


def main():
    setup_logging()
    _setup_crash_reporting()

    parser = argparse.ArgumentParser(description='Attune — Voice Wellness Monitor')
    parser.add_argument('--electron', action='store_true', help='Run in Electron mode (no browser open)')
    args = parser.parse_args()

    attune_app = Attune(electron_mode=args.electron)

    # Handle Ctrl+C and SIGTERM gracefully
    def _sig_handler(sig, frame):
        attune_app._shutdown.set()
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    attune_app.run()


if __name__ == '__main__':
    main()
