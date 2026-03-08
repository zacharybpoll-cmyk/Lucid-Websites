"""
The Pulse — Proactive Notification Engine for Lucid
Delivers macOS notifications for zone transitions, threshold alerts,
milestones, Voice Weather (morning), and Curtain Call (end-of-day).
"""
import logging
import subprocess
import threading
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger('lucid.notifications')


class NotificationManager:
    """Sends macOS notifications with rate limiting and quiet hours."""

    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        # In-memory rate limit tracking (reset on restart is fine)
        self._recent_sends: List[float] = []
        self.MAX_PER_HOUR = 4
        self.MAX_ECHO_PER_DAY = 3  # Max echo-category notifications per day
        # Shutdown event for clean teardown
        self._shutdown_event = threading.Event()
        # Scheduled timer for curtain call
        self._curtain_timer = None
        self._curtain_sent_today = False
        # Track whether voice weather was sent today
        self._weather_sent_today = False
        self._last_weather_date = None
        # Track whether rings-closed notification was sent today
        self._ring_close_notified_today = False
        # Previous zone for transition detection
        self._previous_zone = None

    # ================================================================
    #  Core: send_notification
    # ================================================================

    def send_notification(self, title: str, message: str, subtitle: str = "",
                          sound: bool = True, notif_type: str = "general") -> bool:
        """Send a macOS notification via osascript. Returns True if sent."""
        if not self._can_send(notif_type):
            return False

        # Check if this notification type is enabled
        if not self._is_type_enabled(notif_type):
            return False

        try:
            # Build osascript command
            sound_clause = ' sound name "Blow"' if sound else ''
            subtitle_clause = f' subtitle "{self._escape(subtitle)}"' if subtitle else ''
            script = (
                f'display notification "{self._escape(message)}" '
                f'with title "{self._escape(title)}"{subtitle_clause}{sound_clause}'
            )
            subprocess.Popen(
                ['osascript', '-e', script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Log to DB and track rate
            with self._lock:
                self._recent_sends.append(time.time())
            self.db.log_notification(notif_type, title, message)
            return True
        except Exception as e:
            logger.error(f"Failed to send: {e}")
            return False

    def _can_send(self, notif_type: str) -> bool:
        """Check rate limit and quiet hours."""
        now = datetime.now()

        # Quiet hours check
        quiet_start = int(self.db.get_notification_pref('quiet_start', '20'))
        quiet_end = int(self.db.get_notification_pref('quiet_end', '6'))
        hour = now.hour
        if quiet_start > quiet_end:
            # Spans midnight (e.g., 19-8)
            if hour >= quiet_start or hour < quiet_end:
                return False
        else:
            if quiet_start <= hour < quiet_end:
                return False

        # Rate limit: max N per hour
        with self._lock:
            cutoff = time.time() - 3600
            self._recent_sends = [t for t in self._recent_sends if t > cutoff]
            if len(self._recent_sends) >= self.MAX_PER_HOUR:
                return False

        # Adaptive timing: prefer peak window when enabled
        adaptive_enabled = self.db.get_notification_pref('adaptive_timing', 'false')
        if adaptive_enabled.lower() == 'true' and notif_type not in ('threshold', 'transition'):
            peak = self.get_peak_window()
            if peak['has_data']:
                hour = now.hour
                if not (peak['peak_start'] <= hour < peak['peak_end']):
                    return False

        # Echo-specific daily cap
        if notif_type == 'echo':
            try:
                echo_today = self.db.get_notification_count_today('echo')
                if echo_today >= self.MAX_ECHO_PER_DAY:
                    return False
            except Exception:
                pass  # Non-fatal — fall through if DB unavailable

        return True

    def _is_type_enabled(self, notif_type: str) -> bool:
        """Check if a notification type is enabled in preferences."""
        # Master switch
        master = self.db.get_notification_pref('notifications_enabled', 'true')
        if master.lower() != 'true':
            return False
        # Per-type toggle (default: enabled)
        pref = self.db.get_notification_pref(f'notif_{notif_type}', 'true')
        return pref.lower() == 'true'

    @staticmethod
    def _escape(text: str) -> str:
        """Escape quotes for osascript."""
        return text.replace('\\', '\\\\').replace('"', '\\"')

    # ================================================================
    #  Adaptive Notification Timing
    # ================================================================

    def get_peak_window(self) -> Dict[str, Any]:
        """Compute the peak 2-hour notification engagement window from open history."""
        opens = self.db.get_notification_opens(days=14)
        if len(opens) < 5:
            return {'has_data': False, 'peak_start': 9, 'peak_end': 11}

        # Build hourly histogram
        histogram = [0] * 24
        for o in opens:
            histogram[o['hour']] += 1

        # Find peak 2-hour window
        best_start = 9
        best_count = 0
        for h in range(6, 20):  # Only consider 6 AM to 8 PM
            window_count = histogram[h] + histogram[(h + 1) % 24]
            if window_count > best_count:
                best_count = window_count
                best_start = h

        return {
            'has_data': True,
            'peak_start': best_start,
            'peak_end': best_start + 2,
            'histogram': histogram,
            'total_opens': len(opens),
        }

    # ================================================================
    #  Threshold Alerts — triggered per reading
    # ================================================================

    def check_threshold_alert(self, reading: Dict[str, Any]):
        """Check if the current reading warrants a threshold alert."""
        zone = reading.get('zone', 'steady')
        stress = reading.get('stress_score', 0) or 0

        # Sustained tense/stressed: only alert if zone stayed for multiple readings
        if zone in ('tense', 'stressed') and stress >= 60:
            # Check last 3 readings
            recent = self.db.get_today_readings()[:3]
            if len(recent) >= 3 and all(r.get('zone') in ('tense', 'stressed') for r in recent):
                mins = len(recent) * 5  # approximate
                self.send_notification(
                    "Lucid",
                    f"You've been in the {zone} zone for ~{mins} min. Your voice shows rising stress.",
                    subtitle="Stress Alert",
                    notif_type="threshold"
                )

    # ================================================================
    #  Zone Transition Notifications
    # ================================================================

    def check_zone_transition(self, reading: Dict[str, Any]):
        """Detect zone transitions and notify on positive shifts."""
        current_zone = reading.get('zone', 'steady')

        if self._previous_zone is None:
            self._previous_zone = current_zone
            return

        prev = self._previous_zone
        self._previous_zone = current_zone

        # Positive transitions
        if prev in ('stressed', 'tense') and current_zone == 'calm':
            self.send_notification(
                "Lucid",
                f"You shifted from {prev} to calm. Nice recovery.",
                subtitle="Zone Transition",
                notif_type="transition"
            )
        elif prev == 'stressed' and current_zone == 'steady':
            self.send_notification(
                "Lucid",
                "Stress is easing. You moved from stressed to steady.",
                subtitle="Zone Transition",
                notif_type="transition"
            )

    # ================================================================
    #  Milestone Notifications
    # ================================================================

    def notify_echo_discovered(self, echo_message: str):
        """Notify when a new pattern is discovered."""
        # Truncate to fit notification
        msg = echo_message[:120] if len(echo_message) > 120 else echo_message
        self.send_notification(
            "Lucid",
            msg,
            subtitle="Pattern Discovered",
            notif_type="echo"
        )

    # ================================================================
    #  Streak Insurance Prompt
    # ================================================================

    def prompt_streak_insurance(self, streak: int):
        """Prompt user to use streak insurance when streak is at risk."""
        self.send_notification(
            "Lucid",
            f"Your {streak}-day streak is at risk! Use your resilience day to save it.",
            subtitle="Streak Insurance",
            notif_type="streak_insurance"
        )

    # ================================================================
    #  Voice Weather — Morning Readiness Ritual
    # ================================================================

    def generate_voice_weather(self, reading: Dict[str, Any]):
        """
        Generate and send Voice Weather notification for the first reading of the day.
        Compares current reading to personal baselines and recent weekly average.
        """
        today = date.today()
        if self._last_weather_date == today:
            return  # Already sent today
        self._last_weather_date = today

        stress = reading.get('stress_score', 50) or 50
        energy = reading.get('energy_score', 50) or 50
        mood = reading.get('mood_score', 50) or 50
        calm = reading.get('calm_score', 50) or 50

        # Get weekly averages for comparison
        summaries = self.db.get_daily_summaries(days=7)
        if summaries:
            week_stress = sum(s.get('avg_stress', 50) or 50 for s in summaries) / len(summaries)
        else:
            week_stress = 50

        # Determine weather
        composite = (calm * 0.3 + mood * 0.3 + energy * 0.2 + (100 - stress) * 0.2)

        if composite >= 75:
            weather = "Clear"
            emoji = "\u2600\uFE0F"
            advice = "Good day for deep work."
        elif composite >= 55:
            weather = "Partly Cloudy"
            emoji = "\u26C5"
            advice = "Pace yourself through the morning."
        elif composite >= 35:
            weather = "Overcast"
            emoji = "\U0001F327\uFE0F"
            advice = "Consider lighter meeting load if possible."
        else:
            weather = "Stormy"
            emoji = "\u26C8\uFE0F"
            advice = "Prioritize recovery today."

        # Compare to weekly average
        diff = week_stress - stress
        if abs(diff) >= 5:
            if diff > 0:
                comparison = f"You're starting {abs(diff):.0f}% calmer than your weekly average."
            else:
                comparison = f"Stress is {abs(diff):.0f} points above your weekly average."
        else:
            comparison = "Close to your weekly baseline."

        message = f"{emoji} {weather} — {comparison} {advice}"

        self.send_notification(
            "Voice Weather",
            message,
            subtitle=f"Stress: {stress:.0f} | Energy: {energy:.0f} | Mood: {mood:.0f}",
            notif_type="voice_weather"
        )

    # ================================================================
    #  Curtain Call — End-of-Day Wrap
    # ================================================================

    def schedule_curtain_call(self):
        """Schedule the end-of-day wrap. Called once at app startup."""
        self._schedule_next_curtain()

    def _schedule_next_curtain(self):
        """Schedule curtain call at 5:30pm or reschedule for tomorrow."""
        now = datetime.now()
        target = now.replace(hour=17, minute=30, second=0, microsecond=0)

        if now >= target:
            # Past 5:30pm today — try now if not sent, else schedule tomorrow
            if not self._curtain_sent_today:
                threading.Thread(target=self._fire_curtain_call, daemon=True).start()
            target += timedelta(days=1)

        delay = (target - now).total_seconds()
        if delay > 0:
            self._curtain_timer = threading.Timer(delay, self._fire_curtain_call)
            self._curtain_timer.daemon = True
            self._curtain_timer.start()

    def _fire_curtain_call(self):
        """Generate and send the Curtain Call notification."""
        if self._curtain_sent_today:
            self._schedule_next_curtain()
            return

        try:
            readings = self.db.get_today_readings()
            if not readings or len(readings) < 2:
                self._schedule_next_curtain()
                return

            summary = self.db.compute_daily_summary()
            if not summary:
                self._schedule_next_curtain()
                return

            num_readings = len(readings)
            avg_stress = summary.get('avg_stress', 50) or 50
            calm_min = summary.get('time_in_calm_min', 0) or 0

            # Compare to yesterday
            yesterday = date.today() - timedelta(days=1)
            yesterday_summary = self.db.get_summary_for_date(yesterday)
            if yesterday_summary and yesterday_summary.get('avg_stress'):
                diff = avg_stress - (yesterday_summary.get('avg_stress', 50) or 50)
                if diff > 0:
                    trend = f"\u2191{abs(diff):.0f} from yesterday"
                elif diff < 0:
                    trend = f"\u2193{abs(diff):.0f} from yesterday"
                else:
                    trend = "same as yesterday"
            else:
                trend = ""

            # Find peak stress period
            peak_reading = max(readings, key=lambda r: r.get('stress_score', 0) or 0)
            peak_time = ""
            try:
                peak_dt = datetime.fromisoformat(peak_reading['timestamp'])
                peak_time = peak_dt.strftime("%-I:%M %p")
            except (ValueError, KeyError):
                pass

            # Build message
            parts = [f"{num_readings} readings, avg stress {avg_stress:.0f}"]
            if trend:
                parts[0] += f" ({trend})"
            if calm_min > 0:
                parts.append(f"{calm_min:.0f}m calm time")
            if peak_time:
                parts.append(f"Peak: {peak_time}")

            message = ". ".join(parts) + "."

            self.send_notification(
                "Your Day",
                message,
                subtitle="Curtain Call",
                notif_type="curtain_call"
            )

            self._curtain_sent_today = True
        except Exception as e:
            logger.error(f"Curtain call error: {e}")

        # Schedule for tomorrow
        self._schedule_next_curtain()

    def check_idle_curtain_call(self):
        """
        Called periodically — if it's after 4pm and no reading for 30+ min,
        fire curtain call early (user likely done for the day).
        """
        if self._curtain_sent_today:
            return

        now = datetime.now()
        if now.hour < 16:
            return

        readings = self.db.get_today_readings()
        if not readings:
            return

        # Check time since last reading
        try:
            last_ts = datetime.fromisoformat(readings[0]['timestamp'])
            idle_min = (now - last_ts).total_seconds() / 60
            if idle_min >= 30:
                self._fire_curtain_call()
        except (ValueError, KeyError):
            pass

    # ================================================================
    #  First Reading of Day Detection
    # ================================================================

    def on_new_reading(self, reading: Dict[str, Any]):
        """
        Called after every new reading is saved.
        Dispatches to all notification checks.
        """
        self._check_daily_reset()
        today = date.today()

        # Check if this is the first reading of the day
        readings_today = self.db.get_today_readings()
        if len(readings_today) == 1:
            # First reading — send Voice Weather
            self.generate_voice_weather(reading)
            # Health Score ready notification (teaser — preserves reveal moment)
            self._notify_health_score_ready()

        # Zone transition check
        self.check_zone_transition(reading)

        # Threshold alerts
        self.check_threshold_alert(reading)

        # Idle curtain call check
        self.check_idle_curtain_call()

    # ================================================================
    #  Health Score Ready Notification
    # ================================================================

    def _notify_health_score_ready(self):
        """Notify user their Health Score is ready after first reading of the day."""
        self.send_notification(
            "Lucid",
            "Your first reading is in. Open Lucid to reveal your Health Score.",
            subtitle="Health Score Ready",
            notif_type="voice_weather"
        )

    # ================================================================
    #  Weekly Wrapped Notification
    # ================================================================

    def notify_weekly_wrapped(self):
        """Send notification that weekly wrap is ready (Friday evenings)."""
        today = date.today()
        if today.weekday() != 4:  # Friday
            return
        self.send_notification(
            "Lucid",
            "Your Week in Voice is ready. Tap to see your weekly highlights.",
            subtitle="Weekly Wrapped",
            notif_type="weekly_wrapped"
        )

    # ================================================================
    #  Voice Season Notifications
    # ================================================================

    def notify_phase_transition(self, phase: str, day: int):
        """Notify when entering a new voice season phase."""
        messages = {
            'Patterns': f"Day {day} — Patterns phase unlocked. Your voice has a story forming.",
            'Prediction': f"Day {day} — Prediction phase unlocked. Your voice patterns are maturing.",
        }
        msg = messages.get(phase, f"Day {day} — New phase: {phase}")
        self.send_notification(
            "Voice Season",
            msg,
            subtitle=f"{phase} Unlocked",
            notif_type="voice_season"
        )

    def notify_season_complete(self, season_number: int, total_readings: int):
        """Notify when a voice season is complete."""
        self.send_notification(
            "Voice Season Complete",
            f"Season {season_number} complete! {total_readings} readings over 90 days.",
            subtitle=f"Season {season_number}",
            notif_type="voice_season"
        )

    # ================================================================
    #  Reset Daily State
    # ================================================================

    def _check_daily_reset(self):
        """Auto-reset daily state if the date has changed."""
        today = date.today()
        if self._last_weather_date is not None and self._last_weather_date < today:
            logger.info(f"New day detected ({today}), resetting daily state")
            self.reset_daily_state()

    def reset_daily_state(self):
        """Reset daily flags. Call at midnight or app startup."""
        self._curtain_sent_today = False
        self._weather_sent_today = False
        self._last_weather_date = None
        self._ring_close_notified_today = False

    def stop(self):
        """Cancel pending timers."""
        self._shutdown_event.set()
        if self._curtain_timer:
            self._curtain_timer.cancel()
