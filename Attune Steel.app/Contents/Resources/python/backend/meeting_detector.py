"""
Meeting detector - detects active Zoom/Teams meetings using psutil
"""
import logging
import platform
import psutil
import threading
import time
from typing import Optional, Callable
import app_config as config

logger = logging.getLogger('attune.meeting')


class MeetingDetector:
    def __init__(self, on_meeting_change: Optional[Callable] = None):
        """
        Args:
            on_meeting_change: Callback function called with True/False when meeting state changes
        """
        self.on_meeting_change = on_meeting_change
        self.is_running = False
        self.poll_thread = None
        self._is_macos = platform.system() == 'Darwin'
        # Thread-safe meeting state
        self._state_lock = threading.Lock()
        self._meeting_active = False
        self._manual_override = False
        # TS-003: Shutdown event for graceful thread termination
        self._shutdown_event = threading.Event()

    def start(self):
        """Start meeting detection polling"""
        if self.is_running:
            return

        logger.info("Starting meeting detection")
        self.is_running = True
        self._shutdown_event.clear()
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True,
                                           name="meeting-detector")
        self.poll_thread.start()
        logger.debug("Meeting detector thread started")

    def stop(self):
        """Stop meeting detection polling.
        TS-003: Signals shutdown event and joins thread with timeout."""
        logger.info("Stopping meeting detection")
        self.is_running = False
        self._shutdown_event.set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=5)
            if self.poll_thread.is_alive():
                logger.warning("Meeting detector thread did not stop within timeout")
        logger.debug("Meeting detector stopped")

    def _poll_loop(self):
        """Main polling loop (runs in separate thread).
        TS-003/TS-007: Uses _shutdown_event.wait() instead of time.sleep()
        for immediate shutdown response."""
        logger.debug("Meeting detector poll loop running")
        while not self._shutdown_event.is_set():
            try:
                # Skip detection if manual override is active
                with self._state_lock:
                    override = self._manual_override
                if not override:
                    detected = self._detect_meeting()

                    # Check if state changed
                    with self._state_lock:
                        changed = (detected != self._meeting_active)
                        if changed:
                            self._meeting_active = detected
                    if changed and self.on_meeting_change:
                        self.on_meeting_change(detected)

                # TS-007: Event.wait wakes immediately on shutdown
                self._shutdown_event.wait(timeout=config.MEETING_POLL_INTERVAL_SEC)

            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                self._shutdown_event.wait(timeout=config.MEETING_POLL_INTERVAL_SEC)
        logger.debug("Meeting detector poll loop exited")

    def _detect_meeting(self) -> bool:
        """
        Detect if Zoom or Teams meeting is active

        Returns:
            True if meeting detected, False otherwise
        """
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name'].lower()

                    # Check for Zoom meeting
                    if self._is_macos:
                        # On macOS, zoom.us runs even when idle in the dock.
                        # CptHost is a subprocess Zoom spawns only during an active meeting.
                        if proc_name == 'cpthost':
                            return True
                    else:
                        if 'zoom' in proc_name:
                            return True

                    # Check for Teams meeting
                    if self._is_macos:
                        # Microsoft Teams Helper (Renderer) with audio = active call
                        if 'microsoft teams' in proc_name and 'helper' in proc_name:
                            return True
                    else:
                        if 'teams' in proc_name:
                            return True

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return False

        except Exception as e:
            logger.error(f"Error detecting meeting: {e}")
            return False

    def set_manual_override(self, active: bool):
        """
        Manually set meeting state (overrides automatic detection)

        Args:
            active: True if in meeting, False otherwise
        """
        with self._state_lock:
            self._manual_override = True
            changed = (active != self._meeting_active)
            if changed:
                self._meeting_active = active
        if changed and self.on_meeting_change:
            self.on_meeting_change(active)

        logger.info(f"Manual override: Meeting {'active' if active else 'inactive'}")

    def clear_manual_override(self):
        """Clear manual override and resume automatic detection"""
        with self._state_lock:
            self._manual_override = False
        logger.info("Manual override cleared, resuming automatic detection")

    def is_meeting_active(self) -> bool:
        """Get current meeting state"""
        with self._state_lock:
            return self._meeting_active
