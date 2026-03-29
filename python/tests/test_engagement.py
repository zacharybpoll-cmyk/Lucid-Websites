"""
Tests for backend.engagement.EngagementTracker

Covers milestones, rhythm rings, and CSV export.
"""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from backend.engagement import EngagementTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Create a MagicMock database with common method stubs."""
    db = MagicMock()
    db.get_daily_summaries.return_value = []
    db.get_readings.return_value = []
    db.get_today_readings.return_value = []
    db.get_all_baselines.return_value = {}
    db.get_echoes.return_value = []
    db.get_current_goals.return_value = None
    db.compute_daily_summary.return_value = None
    # Targeted query methods (MEM-002/EFF-001)
    db.count_readings.return_value = 0
    db.get_first_reading_timestamp.return_value = None
    db.count_readings_since.return_value = 0
    db.count_daily_summaries.return_value = 0
    return db


def _make_summary(day_offset=0, **overrides):
    """Build a daily summary dict for (today - day_offset)."""
    d = date.today() - timedelta(days=day_offset)
    base = {
        'date': d.isoformat(),
        'avg_stress': 45.0,
        'avg_mood': 65.0,
        'avg_energy': 55.0,
        'avg_calm': 60.0,
        'peak_stress': 70.0,
        'time_in_calm_min': 30.0,
        'time_in_steady_min': 45.0,
        'time_in_tense_min': 15.0,
        'time_in_stressed_min': 10.0,
        'total_speech_min': 25.0,
        'total_meetings': 3,
    }
    base.update(overrides)
    return base


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
        'meeting_detected': 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Rhythm Rings
# ---------------------------------------------------------------------------

class TestRhythmRings:
    def test_rings_default_goals(self):
        """When no goals exist, default goals are created and rings computed."""
        db = _make_mock_db()
        db.get_current_goals.return_value = None
        db.compute_daily_summary.return_value = {
            'total_speech_min': 10.0,
            'time_in_calm_min': 8.0,
        }
        db.get_today_readings.return_value = [_make_reading() for _ in range(3)]

        tracker = EngagementTracker(db)
        result = tracker.compute_rhythm_rings()

        assert 'speak' in result
        assert 'calm' in result
        assert 'checkin' in result
        assert 'all_closed' in result
        # Default goals are set
        db.set_goals.assert_called_once()

    def test_rings_with_existing_goals(self):
        """With existing goals, rings compute percentages correctly."""
        db = _make_mock_db()
        db.get_current_goals.return_value = {
            'speak_target': 20,
            'calm_target': 15,
            'checkin_target': 5,
        }
        db.compute_daily_summary.return_value = {
            'total_speech_min': 10.0,
            'time_in_calm_min': 7.5,
        }
        db.get_today_readings.return_value = [_make_reading() for _ in range(3)]

        tracker = EngagementTracker(db)
        result = tracker.compute_rhythm_rings()

        assert result['speak']['current'] == 10.0
        assert result['speak']['target'] == 20
        assert result['speak']['pct'] == 50  # 10/20 * 100

        assert result['calm']['current'] == 7.5
        assert result['calm']['target'] == 15
        assert result['calm']['pct'] == 50  # 7.5/15 * 100

        assert result['checkin']['current'] == 3
        assert result['checkin']['target'] == 5
        assert result['checkin']['pct'] == 60  # 3/5 * 100

        assert result['all_closed'] is False

    def test_rings_all_closed(self):
        """All rings at or above target should set all_closed=True."""
        db = _make_mock_db()
        db.get_current_goals.return_value = {
            'speak_target': 10,
            'calm_target': 10,
            'checkin_target': 3,
        }
        db.compute_daily_summary.return_value = {
            'total_speech_min': 15.0,
            'time_in_calm_min': 12.0,
        }
        db.get_today_readings.return_value = [_make_reading() for _ in range(5)]

        tracker = EngagementTracker(db)
        result = tracker.compute_rhythm_rings()

        assert result['speak']['pct'] == 100  # Capped at 100
        assert result['calm']['pct'] == 100
        assert result['checkin']['pct'] == 100
        assert result['all_closed'] is True

    def test_rings_no_summary(self):
        """No summary should yield zero progress."""
        db = _make_mock_db()
        db.get_current_goals.return_value = {
            'speak_target': 15,
            'calm_target': 15,
            'checkin_target': 5,
        }
        db.compute_daily_summary.return_value = None
        db.get_today_readings.return_value = []

        tracker = EngagementTracker(db)
        result = tracker.compute_rhythm_rings()

        assert result['speak']['current'] == 0
        assert result['calm']['current'] == 0
        assert result['checkin']['current'] == 0
        assert result['all_closed'] is False

    def test_rings_data_format(self):
        """Each ring entry has current, target, and pct fields."""
        db = _make_mock_db()
        db.get_current_goals.return_value = {
            'speak_target': 15,
            'calm_target': 15,
            'checkin_target': 5,
        }
        db.compute_daily_summary.return_value = {'total_speech_min': 5.0, 'time_in_calm_min': 3.0}
        db.get_today_readings.return_value = [_make_reading()]

        tracker = EngagementTracker(db)
        result = tracker.compute_rhythm_rings()

        for ring_name in ('speak', 'calm', 'checkin'):
            ring = result[ring_name]
            assert 'current' in ring
            assert 'target' in ring
            assert 'pct' in ring
            assert isinstance(ring['pct'], (int, float))


# ---------------------------------------------------------------------------
# Legacy Milestones
# ---------------------------------------------------------------------------

class TestLegacyMilestones:
    def test_first_reading_milestone(self):
        """With 1+ reading, first_reading milestone is achieved."""
        db = _make_mock_db()
        db.count_readings.return_value = 1
        db.get_first_reading_timestamp.return_value = '2025-01-01T12:00:00'
        tracker = EngagementTracker(db)
        milestones = tracker.compute_milestones()
        first = next(m for m in milestones if m['id'] == 'first_reading')
        assert first['achieved'] is True

    def test_no_readings_no_milestones(self):
        """With no readings, first_reading is not achieved."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        milestones = tracker.compute_milestones()
        first = next(m for m in milestones if m['id'] == 'first_reading')
        assert first['achieved'] is False

    def test_milestones_count(self):
        """There should be exactly 5 milestones."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        milestones = tracker.compute_milestones()
        assert len(milestones) == 5


# ---------------------------------------------------------------------------
# Engagement Summary
# ---------------------------------------------------------------------------

class TestEngagementSummary:
    def test_summary_structure(self):
        """get_engagement_summary returns expected keys."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        summary = tracker.get_engagement_summary()
        assert 'milestones' in summary
        assert 'total_readings' in summary
        assert 'total_days' in summary
        assert 'total_meetings' in summary
        assert 'streak' not in summary


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

class TestCSVExport:
    def test_export_readings_no_data(self):
        """No readings returns 'No data to export'."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        result = tracker.export_readings_csv()
        assert result == "No data to export"

    def test_export_readings_with_data(self):
        """With readings, CSV contains headers and data rows."""
        db = _make_mock_db()
        db.get_readings.return_value = [
            {'timestamp': '2025-01-01T12:00:00', 'stress_score': 45.0, 'zone': 'steady'},
            {'timestamp': '2025-01-01T13:00:00', 'stress_score': 55.0, 'zone': 'tense'},
        ]
        tracker = EngagementTracker(db)
        result = tracker.export_readings_csv()
        assert 'timestamp' in result
        assert 'stress_score' in result
        assert '45.0' in result
        assert '55.0' in result

    def test_export_summaries_no_data(self):
        """No summaries returns 'No data to export'."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        result = tracker.export_summaries_csv()
        assert result == "No data to export"
