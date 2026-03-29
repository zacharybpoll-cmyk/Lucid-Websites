"""
Analytics engine — queues events and flushes to Supabase in batches.

Features:
- Anonymous UUID generated on first launch (stored in user_state)
- In-memory event queue with 30s batch flush
- Offline fallback to pending_analytics.json
- 10,000 event queue cap (drops oldest on overflow)
"""
import json
import logging
import platform
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional, Dict, Any

from backend.supabase_client import SupabaseClient

logger = logging.getLogger('lucid.analytics')

MAX_QUEUE_SIZE = 10_000
PENDING_FILENAME = "pending_analytics.json"


class AnalyticsEngine:
    """Centralized analytics with batched Supabase writes."""

    def __init__(self, supabase_url: str, supabase_key: str,
                 data_dir: Path, app_version: str,
                 flush_interval: int = 30,
                 db=None):
        self.app_version = app_version
        self.os_version = f"macOS {platform.mac_ver()[0]}"
        self.data_dir = data_dir
        self.flush_interval = flush_interval
        self._db = db

        # Supabase client
        self._client = SupabaseClient(supabase_url, supabase_key)

        # Event queue (thread-safe deque)
        self._queue: deque = deque(maxlen=MAX_QUEUE_SIZE)
        self._error_queue: deque = deque(maxlen=1000)
        self._lock = threading.Lock()

        # Anonymous user ID
        self._user_id: Optional[str] = None
        self._is_first_launch: bool = False

        # Session timing
        self._session_start: float = time.time()

        # Flush thread
        self._shutdown = threading.Event()
        self._flush_thread: Optional[threading.Thread] = None

        # Daily summary tracking
        self._daily_readings_count = 0
        self._daily_speech_min = 0.0
        self._daily_views: set = set()
        self._daily_features: set = set()
        self._daily_sessions = 0
        self._daily_date: Optional[str] = None

    @property
    def user_id(self) -> str:
        """Get or create anonymous user ID."""
        if self._user_id is None:
            self._user_id = self._load_or_create_user_id()
        return self._user_id

    def _load_or_create_user_id(self) -> str:
        """Load user ID from DB user_state, or create and persist a new one."""
        if self._db:
            existing = self._db.get_user_state('anonymous_user_id', '')
            if existing:
                return existing
        # Generate new UUID — this is a first launch
        new_id = str(uuid.uuid4())
        self._is_first_launch = True
        if self._db:
            self._db.set_user_state('anonymous_user_id', new_id)
        logger.info(f"Generated anonymous analytics ID: {new_id[:8]}...")
        return new_id

    def start(self):
        """Start the background flush thread."""
        if self._flush_thread and self._flush_thread.is_alive():
            return
        self._shutdown.clear()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="analytics-flush"
        )
        self._flush_thread.start()
        logger.info(f"Analytics engine started (flush every {self.flush_interval}s)")

        # Register user on first start
        self._register_user()

        # Fire first_launch event if this is a new install
        if self._is_first_launch:
            self.track("first_launch", {
                "app_version": self.app_version,
                "os_version": self.os_version,
            })

    def stop(self):
        """Stop flush thread and do a final flush."""
        # Track session duration
        duration = round(time.time() - self._session_start)
        self.track("session_end", {"duration_seconds": duration})

        self._shutdown.set()
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5)
        # Final flush
        self._flush()
        self._client.close()
        logger.info("Analytics engine stopped")

    def track_onboarding(self, step_name: str, step_number: int):
        """Track onboarding step completion."""
        self.track("onboarding_step", {
            "step_name": step_name,
            "step_number": step_number,
        })

    def track(self, event_type: str, payload: Optional[Dict[str, Any]] = None):
        """Enqueue an analytics event."""
        event = {
            "user_id": self.user_id,
            "event_type": event_type,
            "timestamp": _now_iso(),
            "app_version": self.app_version,
            "payload": payload or {},
        }
        self._queue.append(event)

        # Update daily counters
        self._update_daily_counters(event_type, payload)

    def track_error(self, error_type: str, error_message: str,
                    context: str = ""):
        """Enqueue an error event."""
        error = {
            "user_id": self.user_id,
            "timestamp": _now_iso(),
            "error_type": error_type,
            "error_message": error_message[:500],  # Truncate
            "context": context[:200],
            "app_version": self.app_version,
        }
        self._error_queue.append(error)

    def _register_user(self):
        """Upsert user record in Supabase."""
        try:
            self._client.upsert_user(
                self.user_id, self.app_version, self.os_version
            )
        except Exception as e:
            logger.debug(f"User registration deferred: {e}")

    def _update_daily_counters(self, event_type: str,
                               payload: Optional[Dict]):
        """Track daily aggregates for analytics_daily."""
        today = date.today().isoformat()
        if self._daily_date != today:
            # New day — reset counters
            self._daily_date = today
            self._daily_readings_count = 0
            self._daily_speech_min = 0.0
            self._daily_views = set()
            self._daily_features = set()
            self._daily_sessions = 0

        if event_type == "voice_reading":
            self._daily_readings_count += 1
            if payload and "speech_duration_sec" in payload:
                self._daily_speech_min += payload["speech_duration_sec"] / 60.0
        elif event_type == "view_switch" and payload:
            self._daily_views.add(payload.get("to_view", ""))
        elif event_type == "feature_interact" and payload:
            self._daily_features.add(payload.get("feature", ""))
        elif event_type == "app_launch":
            self._daily_sessions += 1

    def _flush_loop(self):
        """Background loop: flush queue every N seconds."""
        while not self._shutdown.is_set():
            self._shutdown.wait(self.flush_interval)
            if self._shutdown.is_set():
                break
            self._flush()

    def _flush(self):
        """Flush queued events and errors to Supabase."""
        # Drain pending file first (offline events from previous sessions)
        self._drain_pending_file()

        # Drain event queue
        events = []
        while self._queue:
            try:
                events.append(self._queue.popleft())
            except IndexError:
                break

        errors = []
        while self._error_queue:
            try:
                errors.append(self._error_queue.popleft())
            except IndexError:
                break

        if not events and not errors:
            return

        # Ensure user exists before inserting events (FK constraint)
        self._client.upsert_user(self.user_id, self.app_version, self.os_version)

        # Try to send events
        events_ok = True
        if events:
            events_ok = self._client.insert_events(events)

        errors_ok = True
        if errors:
            errors_ok = self._client.insert_errors(errors)

        # If send failed, save to pending file for later
        if not events_ok and events:
            self._save_pending(events, "events")
        if not errors_ok and errors:
            self._save_pending(errors, "errors")

        # Flush daily summary
        self._flush_daily_summary()

        if events_ok and errors_ok:
            count = len(events) + len(errors)
            if count > 0:
                logger.debug(f"Flushed {len(events)} events, {len(errors)} errors")

    def _flush_daily_summary(self):
        """Upsert today's daily summary."""
        if not self._daily_date:
            return
        summary = {
            "user_id": self.user_id,
            "date": self._daily_date,
            "readings_count": self._daily_readings_count,
            "total_speech_min": round(self._daily_speech_min, 1),
            "views_visited": list(self._daily_views),
            "features_used": list(self._daily_features),
            "session_count": self._daily_sessions,
        }
        self._client.upsert_daily(summary)

    def _save_pending(self, items: list, category: str):
        """Save failed items to pending file for later retry."""
        pending_path = self.data_dir / PENDING_FILENAME
        try:
            existing = []
            if pending_path.exists():
                raw = pending_path.read_text()
                if raw.strip():
                    existing = json.loads(raw)
            existing.extend({"category": category, "data": item} for item in items)
            # Cap pending file at 10k entries
            if len(existing) > MAX_QUEUE_SIZE:
                existing = existing[-MAX_QUEUE_SIZE:]
            pending_path.write_text(json.dumps(existing))
            logger.debug(f"Saved {len(items)} pending {category} to disk")
        except Exception as e:
            logger.warning(f"Failed to save pending analytics: {e}")

    def _drain_pending_file(self):
        """Load and send pending events from previous offline sessions."""
        pending_path = self.data_dir / PENDING_FILENAME
        if not pending_path.exists():
            return

        try:
            raw = pending_path.read_text()
            if not raw.strip():
                return
            items = json.loads(raw)
        except Exception as e:
            logger.warning(f"Failed to read pending analytics: {e}")
            return

        if not items:
            return

        events = [i["data"] for i in items if i.get("category") == "events"]
        errors = [i["data"] for i in items if i.get("category") == "errors"]

        events_ok = self._client.insert_events(events) if events else True
        errors_ok = self._client.insert_errors(errors) if errors else True

        if events_ok and errors_ok:
            # All sent — delete pending file
            try:
                pending_path.unlink()
                logger.info(f"Drained {len(events)} pending events, {len(errors)} pending errors")
            except Exception:
                pass
        else:
            logger.debug("Pending analytics not fully drained, will retry next flush")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
