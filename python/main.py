#!/usr/bin/env python3
"""
Attune - Main Entry Point
Browser-based: starts uvicorn, loads models in background, opens browser automatically.
Includes The Beacon (dynamic menubar icon) and The Pulse (notification engine).
"""
import sys
import signal
import threading
import time
import argparse
import webbrowser
from pathlib import Path
from backend.database import Database
from backend.analysis_orchestrator import AnalysisOrchestrator
from backend.meeting_detector import MeetingDetector
from backend.insight_engine import InsightEngine
from backend.notifications import NotificationManager
import app_config as config

# Import API routes and set global references
import api.routes as routes
import uvicorn


# ============ The Beacon — Dynamic Menubar Icon ============

def _create_beacon_icons():
    """Generate colored dot icons for menubar using PIL."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("[Beacon] PIL not available, menubar icons disabled")
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
        print("=" * 60)
        print("Attune — Attuned to you.")
        print("=" * 60)

        # --- Fast init (< 1s) ---
        print("[Main] Initializing database...")
        self.db = Database(config.DB_PATH)
        print(f"[Main] Database ready at {config.DB_PATH}")

        # Create orchestrator with lazy model loading (fast)
        print("[Main] Creating orchestrator (models will load in background)...")
        self.orchestrator = AnalysisOrchestrator(self.db, lazy=True)

        # Create meeting detector
        def on_meeting_change(active):
            if self.orchestrator:
                self.orchestrator.set_meeting_active(active)
        self.meeting_detector = MeetingDetector(on_meeting_change=on_meeting_change)

        # Create insight engine
        print("[Main] Initializing insight engine...")
        self.insight_engine = InsightEngine()

        # Create notification manager (The Pulse)
        print("[Main] Initializing notification engine...")
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
        print(f"[Main] Starting server on http://{config.API_HOST}:{config.API_PORT}")
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

        # Give uvicorn a moment to bind — if it exits, the port is likely in use
        time.sleep(1.5)
        if not server_thread.is_alive():
            print(f"[Main] ERROR: Server failed to start. Port {config.API_PORT} is likely in use.")
            print(f"[Main] Run: lsof -ti :{config.API_PORT} | xargs kill -9")
            sys.exit(1)

        # --- Load models in background thread ---
        def _load_models():
            try:
                self.orchestrator.load_models()
                print("[Main] Models loaded - starting analysis pipeline")
                self.orchestrator.start()
                self.meeting_detector.start()
            except Exception as e:
                print(f"[Main] Model loading failed: {e}")
                import traceback
                traceback.print_exc()

        model_thread = threading.Thread(target=_load_models, daemon=True)
        model_thread.start()

        # --- Wait for server to respond, then open browser (unless --electron) ---
        if not self.electron_mode:
            url = f"http://{config.API_HOST}:{config.API_PORT}/static/index.html"
            self._wait_for_server(url=f"http://{config.API_HOST}:{config.API_PORT}/")
            print(f"[Main] Opening browser at {url}")
            webbrowser.open(url)

        # --- Block until signal ---
        mode_label = "Electron" if self.electron_mode else "Ctrl+C"
        print(f"[Main] Running ({mode_label} mode). Waiting for shutdown signal.")
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
        print("[Main] Warning: server did not respond within timeout, opening browser anyway")

    def _cleanup(self):
        print("\n[Main] Shutting down...")
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
        print("[Main] Goodbye.")

    def update_beacon(self, zone: str):
        """Update the menubar beacon icon color based on current zone."""
        if zone == self._beacon_current_zone:
            return
        self._beacon_current_zone = zone
        # Beacon icons are informational only (no pystray in browser mode)
        # The actual icon state is tracked and available via /api/status


def main():
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
