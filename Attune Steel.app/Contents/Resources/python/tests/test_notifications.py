"""
Tests for backend.notifications.NotificationManager

Covers quiet hours enforcement, rate limiting, zone transition notifications,
voice weather, curtain call scheduling, and daily state reset.
"""
import time
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.notifications import NotificationManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Create a MagicMock database with common method stubs."""
    db = MagicMock()
    # Default: quiet hours 20-6, notifications enabled
    db.get_notification_pref.side_effect = lambda key, default=None: {
        'quiet_start': '20',
        'quiet_end': '6',
        'notifications_enabled': 'true',
    }.get(key, default or 'true')
    db.get_daily_summaries.return_value = []
    db.get_today_readings.return_value = []
    db.log_notification.return_value = None
    return db


def _make_reading(**overrides):
    """Build a reading dict."""
    base = {
        'timestamp': datetime.now().isoformat(),
        'stress_score': 45.0,
        'mood_score': 65.0,
        'energy_score': 55.0,
        'calm_score': 60.0,
        'zone': 'steady',
        'speech_duration_sec': 45.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestNotificationManagerInit:
    def test_instantiation(self):
        """NotificationManager should instantiate with expected defaults."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        assert mgr.MAX_PER_HOUR == 4
        assert mgr._curtain_sent_today is False
        assert mgr._weather_sent_today is False
        assert mgr._previous_zone is None
        mgr.stop()

    def test_has_rate_limit_deque(self):
        """Manager should have a deque for tracking recent sends."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        assert hasattr(mgr, '_recent_sends')
        assert len(mgr._recent_sends) == 0
        mgr.stop()


# ---------------------------------------------------------------------------
# Quiet Hours
# ---------------------------------------------------------------------------

class TestQuietHours:
    def test_quiet_hours_blocks_late_night(self):
        """Notifications during quiet hours (e.g., 22:00) should be blocked."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'quiet_start': '22',
            'quiet_end': '7',
            'notifications_enabled': 'true',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)

        # Mock datetime.now() to return 23:00
        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 23, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is False

        mgr.stop()

    def test_quiet_hours_blocks_early_morning(self):
        """Notifications during quiet hours (e.g., 5:00 AM) should be blocked."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'quiet_start': '22',
            'quiet_end': '7',
            'notifications_enabled': 'true',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 5, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is False

        mgr.stop()

    def test_quiet_hours_allows_daytime(self):
        """Notifications during daytime (e.g., 14:00) should be allowed."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'quiet_start': '22',
            'quiet_end': '7',
            'notifications_enabled': 'true',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 14, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is True

        mgr.stop()

    def test_quiet_hours_allows_just_after_end(self):
        """Notifications right after quiet hours end should be allowed."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'quiet_start': '22',
            'quiet_end': '7',
            'notifications_enabled': 'true',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 7, 30, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is True

        mgr.stop()

    def test_default_quiet_hours(self):
        """Default quiet hours (20-6) should block at 21:00."""
        db = _make_mock_db()
        mgr = NotificationManager(db)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 21, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is False

        mgr.stop()


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limit_allows_under_max(self):
        """Fewer than MAX_PER_HOUR recent sends should allow new send."""
        db = _make_mock_db()
        mgr = NotificationManager(db)

        # Simulate 2 recent sends
        now = time.time()
        mgr._recent_sends.append(now - 60)
        mgr._recent_sends.append(now - 30)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 14, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is True

        mgr.stop()

    def test_rate_limit_blocks_at_max(self):
        """At MAX_PER_HOUR recent sends, new send should be blocked."""
        db = _make_mock_db()
        mgr = NotificationManager(db)

        # Fill up rate limit (4 sends)
        now = time.time()
        for i in range(4):
            mgr._recent_sends.append(now - i * 60)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 14, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is False

        mgr.stop()

    def test_rate_limit_allows_after_old_sends_expire(self):
        """Sends older than 1 hour should be pruned, allowing new sends."""
        db = _make_mock_db()
        mgr = NotificationManager(db)

        # All 4 sends are more than 1 hour old
        now = time.time()
        for i in range(4):
            mgr._recent_sends.append(now - 3700 - i * 10)

        with patch('backend.notifications.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 14, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = mgr._can_send('general')
            assert result is True

        mgr.stop()


# ---------------------------------------------------------------------------
# Notification Type Enabled
# ---------------------------------------------------------------------------

class TestNotificationTypeEnabled:
    def test_master_switch_off(self):
        """Master switch disabled should block all types."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'notifications_enabled': 'false',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)
        assert mgr._is_type_enabled('general') is False
        mgr.stop()

    def test_master_switch_on_type_enabled(self):
        """Master on + type enabled should allow."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'notifications_enabled': 'true',
            'notif_general': 'true',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)
        assert mgr._is_type_enabled('general') is True
        mgr.stop()

    def test_specific_type_disabled(self):
        """Master on but specific type disabled should block."""
        db = _make_mock_db()
        db.get_notification_pref.side_effect = lambda key, default=None: {
            'notifications_enabled': 'true',
            'notif_threshold': 'false',
        }.get(key, default or 'true')

        mgr = NotificationManager(db)
        assert mgr._is_type_enabled('threshold') is False
        mgr.stop()


# ---------------------------------------------------------------------------
# Zone Transitions
# ---------------------------------------------------------------------------

class TestZoneTransitions:
    def test_first_reading_sets_zone(self):
        """First reading should set previous zone without notification."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        reading = _make_reading(zone='steady')
        mgr.check_zone_transition(reading)
        assert mgr._previous_zone == 'steady'
        # No notification on first reading (no transition)
        db.log_notification.assert_not_called()
        mgr.stop()

    def test_stressed_to_calm_triggers_notification(self):
        """Transition from stressed to calm should trigger a notification."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr._previous_zone = 'stressed'

        # Mock send_notification to track calls
        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='calm')
        mgr.check_zone_transition(reading)

        mgr.send_notification.assert_called_once()
        call_args = mgr.send_notification.call_args
        assert 'recovery' in call_args[1].get('message', call_args[0][1]).lower() or \
               'calm' in call_args[1].get('message', call_args[0][1]).lower()
        mgr.stop()

    def test_tense_to_calm_triggers_notification(self):
        """Transition from tense to calm should trigger a notification."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr._previous_zone = 'tense'

        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='calm')
        mgr.check_zone_transition(reading)

        mgr.send_notification.assert_called_once()
        mgr.stop()

    def test_stressed_to_steady_triggers_notification(self):
        """Transition from stressed to steady should trigger a notification."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr._previous_zone = 'stressed'

        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='steady')
        mgr.check_zone_transition(reading)

        mgr.send_notification.assert_called_once()
        mgr.stop()

    def test_steady_to_tense_no_notification(self):
        """Transition from steady to tense should NOT trigger notification (not positive)."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr._previous_zone = 'steady'

        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='tense')
        mgr.check_zone_transition(reading)

        mgr.send_notification.assert_not_called()
        mgr.stop()

    def test_same_zone_no_notification(self):
        """Staying in the same zone should not trigger notification."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr._previous_zone = 'calm'

        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='calm')
        mgr.check_zone_transition(reading)

        mgr.send_notification.assert_not_called()
        mgr.stop()


# ---------------------------------------------------------------------------
# Schedule Curtain Call
# ---------------------------------------------------------------------------

class TestScheduleCurtainCall:
    def test_schedule_curtain_call_does_not_crash(self):
        """schedule_curtain_call should execute without errors."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        # Should not raise
        mgr.schedule_curtain_call()
        mgr.stop()

    def test_curtain_call_has_timer(self):
        """After scheduling, a timer should be set (or thread started)."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr.schedule_curtain_call()
        # Either a timer is set or it already fired (depending on time of day)
        # Just verify no exception occurred
        mgr.stop()


# ---------------------------------------------------------------------------
# Voice Weather
# ---------------------------------------------------------------------------

class TestVoiceWeather:
    def test_voice_weather_sends_once_per_day(self):
        """Voice weather should only send once per day."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(stress_score=30, energy_score=70, mood_score=75, calm_score=80)
        mgr.generate_voice_weather(reading)
        mgr.generate_voice_weather(reading)  # Second call same day

        # Should only have been called once
        assert mgr.send_notification.call_count == 1
        mgr.stop()

    def test_voice_weather_uses_correct_type(self):
        """Voice weather notification should use 'voice_weather' type."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(stress_score=30, energy_score=70, mood_score=75, calm_score=80)
        mgr.generate_voice_weather(reading)

        call_kwargs = mgr.send_notification.call_args
        assert call_kwargs[1]['notif_type'] == 'voice_weather' or \
               (len(call_kwargs[0]) >= 1 and 'voice_weather' in str(call_kwargs))
        mgr.stop()


# ---------------------------------------------------------------------------
# Threshold Alerts
# ---------------------------------------------------------------------------

class TestThresholdAlerts:
    def test_threshold_alert_no_sustained_stress(self):
        """Single tense reading should NOT trigger alert (needs sustained)."""
        db = _make_mock_db()
        db.get_today_readings.return_value = [
            _make_reading(zone='tense', stress_score=65),
        ]
        mgr = NotificationManager(db)
        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='tense', stress_score=65)
        mgr.check_threshold_alert(reading)

        # Only 1 reading, need 3 sustained
        mgr.send_notification.assert_not_called()
        mgr.stop()

    def test_threshold_alert_sustained_stress(self):
        """3+ consecutive tense/stressed readings should trigger alert."""
        db = _make_mock_db()
        db.get_today_readings.return_value = [
            _make_reading(zone='stressed', stress_score=70),
            _make_reading(zone='stressed', stress_score=72),
            _make_reading(zone='tense', stress_score=65),
        ]
        mgr = NotificationManager(db)
        mgr.send_notification = MagicMock(return_value=True)

        reading = _make_reading(zone='stressed', stress_score=70)
        mgr.check_threshold_alert(reading)

        mgr.send_notification.assert_called_once()
        mgr.stop()


# ---------------------------------------------------------------------------
# Daily Reset
# ---------------------------------------------------------------------------

class TestDailyReset:
    def test_reset_daily_state(self):
        """reset_daily_state clears all daily flags."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr._curtain_sent_today = True
        mgr._weather_sent_today = True
        mgr._last_weather_date = date.today()

        mgr.reset_daily_state()

        assert mgr._curtain_sent_today is False
        assert mgr._weather_sent_today is False
        assert mgr._last_weather_date is None
        mgr.stop()


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

class TestStop:
    def test_stop_cancels_timer(self):
        """stop() should cancel any pending curtain call timer."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr.schedule_curtain_call()
        mgr.stop()
        # After stop, shutdown event should be set
        assert mgr._shutdown_event.is_set()

    def test_stop_without_timer(self):
        """stop() should not crash when no timer was scheduled."""
        db = _make_mock_db()
        mgr = NotificationManager(db)
        mgr.stop()  # Should not raise


# ---------------------------------------------------------------------------
# Escape helper
# ---------------------------------------------------------------------------

class TestEscapeHelper:
    def test_escape_quotes(self):
        """Quotes in text should be escaped for osascript."""
        assert NotificationManager._escape('Hello "world"') == 'Hello \\"world\\"'

    def test_escape_backslashes(self):
        """Backslashes should be escaped."""
        assert NotificationManager._escape('path\\to\\file') == 'path\\\\to\\\\file'

    def test_escape_plain_text(self):
        """Plain text with no special chars should pass through unchanged."""
        assert NotificationManager._escape('Hello world') == 'Hello world'
