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
        self.meeting_active = False
        self.poll_thread = None
        self.manual_override = False
        self._is_macos = platform.system() == 'Darwin'

    def start(self):
        """Start meeting detection polling"""
        if self.is_running:
            return

        logger.info("Starting meeting detection")
        self.is_running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def stop(self):
        """Stop meeting detection polling"""
        logger.info("Stopping meeting detection")
        self.is_running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=2)

    def _poll_loop(self):
        """Main polling loop (runs in separate thread)"""
        while self.is_running:
            try:
                # Skip detection if manual override is active
                if not self.manual_override:
                    detected = self._detect_meeting()

                    # Check if state changed
                    if detected != self.meeting_active:
                        self.meeting_active = detected
                        if self.on_meeting_change:
                            self.on_meeting_change(detected)

                time.sleep(config.MEETING_POLL_INTERVAL_SEC)

            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                time.sleep(config.MEETING_POLL_INTERVAL_SEC)

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
        self.manual_override = True
        if active != self.meeting_active:
            self.meeting_active = active
            if self.on_meeting_change:
                self.on_meeting_change(active)

        logger.info(f"Manual override: Meeting {'active' if active else 'inactive'}")

    def clear_manual_override(self):
        """Clear manual override and resume automatic detection"""
        self.manual_override = False
        logger.info("Manual override cleared, resuming automatic detection")

    def is_meeting_active(self) -> bool:
        """Get current meeting state"""
        return self.meeting_active
