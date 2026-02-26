"""
Tests for backend.engagement.EngagementTracker

Covers streak computation, grove growth/wilting, waypoints milestones,
rhythm rings, and CSV export.
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
    db.get_grove_trees.return_value = []
    db.get_user_state.return_value = '1'
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
# Streak Computation
# ---------------------------------------------------------------------------

class TestComputeStreak:
    def test_zero_streak_no_data(self):
        """No summaries should return streak of 0."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        assert tracker.compute_streak() == 0

    def test_zero_streak_no_today(self):
        """Summaries exist but none for today should return 0."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=1),
            _make_summary(day_offset=2),
        ]
        tracker = EngagementTracker(db)
        assert tracker.compute_streak() == 0

    def test_one_day_streak(self):
        """Only today's summary should yield streak of 1."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=0),
        ]
        tracker = EngagementTracker(db)
        assert tracker.compute_streak() == 1

    def test_consecutive_days_streak(self):
        """Consecutive days including today should count correctly."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=0),
            _make_summary(day_offset=1),
            _make_summary(day_offset=2),
            _make_summary(day_offset=3),
        ]
        tracker = EngagementTracker(db)
        assert tracker.compute_streak() == 4

    def test_gap_breaks_streak(self):
        """A gap in days should break the streak."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=0),
            _make_summary(day_offset=1),
            # Day offset 2 is missing (gap)
            _make_summary(day_offset=3),
            _make_summary(day_offset=4),
        ]
        tracker = EngagementTracker(db)
        assert tracker.compute_streak() == 2  # Only today + yesterday

    def test_seven_day_streak(self):
        """7 consecutive days should return 7."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=i) for i in range(7)
        ]
        tracker = EngagementTracker(db)
        assert tracker.compute_streak() == 7


# ---------------------------------------------------------------------------
# Grove
# ---------------------------------------------------------------------------

class TestUpdateGrove:
    def test_grove_no_data(self):
        """No summaries should return current grove state unchanged."""
        db = _make_mock_db()
        db.get_grove_trees.return_value = []
        tracker = EngagementTracker(db)
        result = tracker.update_grove()
        assert 'trees' in result
        assert 'rainfall' in result
        assert result['total_trees'] == 0

    def test_grove_state_structure(self):
        """get_grove_state returns expected keys."""
        db = _make_mock_db()
        db.get_grove_trees.return_value = [
            {'date': date.today().isoformat(), 'tree_state': 'growing', 'growth_stage': 1},
        ]
        tracker = EngagementTracker(db)
        state = tracker.get_grove_state()
        assert 'trees' in state
        assert 'rainfall' in state
        assert 'wilted_count' in state
        assert 'growing_count' in state
        assert 'total_trees' in state
        assert state['growing_count'] == 1
        assert state['wilted_count'] == 0

    def test_grove_counts_wilted(self):
        """Wilted trees are counted separately."""
        db = _make_mock_db()
        db.get_grove_trees.return_value = [
            {'date': '2025-01-01', 'tree_state': 'growing', 'growth_stage': 2},
            {'date': '2025-01-02', 'tree_state': 'wilted', 'growth_stage': 0},
            {'date': '2025-01-03', 'tree_state': 'wilted', 'growth_stage': 0},
        ]
        tracker = EngagementTracker(db)
        state = tracker.get_grove_state()
        assert state['growing_count'] == 1
        assert state['wilted_count'] == 2
        assert state['total_trees'] == 3

    def test_grove_adds_trees_for_active_days(self):
        """update_grove should call add_grove_tree for new active days."""
        db = _make_mock_db()
        today = date.today()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=0),
        ]
        db.get_grove_trees.return_value = []  # No existing trees
        db.get_user_state.return_value = '1'

        tracker = EngagementTracker(db)
        tracker.update_grove()

        # Should have called add_grove_tree for today
        db.add_grove_tree.assert_called()


# ---------------------------------------------------------------------------
# Revive Tree
# ---------------------------------------------------------------------------

class TestReviveTree:
    def test_revive_no_rainfall(self):
        """Cannot revive without rainfall."""
        db = _make_mock_db()
        db.get_user_state.return_value = '0'
        tracker = EngagementTracker(db)
        result = tracker.revive_tree('2025-01-01')
        assert result['success'] is False
        assert 'No rainfall' in result['message']

    def test_revive_no_wilted_tree(self):
        """Cannot revive a non-existent wilted tree."""
        db = _make_mock_db()
        db.get_user_state.return_value = '3'
        db.get_grove_trees.return_value = [
            {'date': '2025-01-01', 'tree_state': 'growing', 'growth_stage': 2},
        ]
        tracker = EngagementTracker(db)
        result = tracker.revive_tree('2025-01-01')
        assert result['success'] is False

    def test_revive_success(self):
        """Reviving a wilted tree consumes rainfall and returns success."""
        db = _make_mock_db()
        db.get_user_state.return_value = '3'
        db.get_grove_trees.return_value = [
            {'date': '2025-01-05', 'tree_state': 'wilted', 'growth_stage': 0},
        ]
        tracker = EngagementTracker(db)
        result = tracker.revive_tree('2025-01-05')
        assert result['success'] is True
        assert result['rainfall_remaining'] == 2
        db.update_grove_tree.assert_called_once_with('2025-01-05', state='growing', stage=1, revived=1)
        db.set_user_state.assert_called_with('rainfall', '2')


# ---------------------------------------------------------------------------
# Waypoints
# ---------------------------------------------------------------------------

class TestWaypoints:
    def test_waypoints_structure(self):
        """compute_waypoints returns expected structure."""
        db = _make_mock_db()
        # Mock the conn for best_canopy query
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'max_score': None}
        db.conn.cursor.return_value = mock_cursor

        tracker = EngagementTracker(db)
        result = tracker.compute_waypoints()

        assert 'waypoints' in result
        assert 'by_tier' in result
        assert 'total' in result
        assert 'achieved' in result
        assert 'progress_pct' in result
        assert result['total'] == 30  # 30 waypoints defined

    def test_auto_waypoints_always_achieved(self):
        """Waypoints marked auto=True are always achieved."""
        db = _make_mock_db()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'max_score': None}
        db.conn.cursor.return_value = mock_cursor

        tracker = EngagementTracker(db)
        result = tracker.compute_waypoints()

        auto_wps = [w for w in result['waypoints'] if w['id'] in ('wp_welcome', 'wp_first_voice')]
        assert len(auto_wps) == 2
        assert all(w['achieved'] for w in auto_wps)

    def test_waypoints_3_readings_achieved(self):
        """With 3+ readings, 'wp_3_readings' should be achieved."""
        db = _make_mock_db()
        db.count_readings.return_value = 5
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'max_score': None}
        db.conn.cursor.return_value = mock_cursor

        tracker = EngagementTracker(db)
        result = tracker.compute_waypoints()

        wp_3 = next(w for w in result['waypoints'] if w['id'] == 'wp_3_readings')
        assert wp_3['achieved'] is True

    def test_waypoints_no_readings_not_achieved(self):
        """With 0 readings, 'wp_3_readings' should not be achieved."""
        db = _make_mock_db()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'max_score': None}
        db.conn.cursor.return_value = mock_cursor

        tracker = EngagementTracker(db)
        result = tracker.compute_waypoints()

        wp_3 = next(w for w in result['waypoints'] if w['id'] == 'wp_3_readings')
        assert wp_3['achieved'] is False

    def test_waypoints_grouped_by_tier(self):
        """by_tier should group waypoints into the expected tier names."""
        db = _make_mock_db()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'max_score': None}
        db.conn.cursor.return_value = mock_cursor

        tracker = EngagementTracker(db)
        result = tracker.compute_waypoints()

        expected_tiers = ['Seedling', 'Sapling', 'Young Tree', 'Mature Tree', 'Old Growth', 'Ancient']
        assert set(result['by_tier'].keys()) == set(expected_tiers)

    def test_waypoints_persisted_to_db(self):
        """Each waypoint should be upserted to the database."""
        db = _make_mock_db()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'max_score': None}
        db.conn.cursor.return_value = mock_cursor

        tracker = EngagementTracker(db)
        tracker.compute_waypoints()

        assert db.upsert_achievement.call_count == 30


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
        """There should be exactly 7 legacy milestones."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        milestones = tracker.compute_milestones()
        assert len(milestones) == 7


# ---------------------------------------------------------------------------
# Engagement Summary
# ---------------------------------------------------------------------------

class TestEngagementSummary:
    def test_summary_structure(self):
        """get_engagement_summary returns expected keys."""
        db = _make_mock_db()
        tracker = EngagementTracker(db)
        summary = tracker.get_engagement_summary()
        assert 'streak' in summary
        assert 'milestones' in summary
        assert 'total_readings' in summary
        assert 'total_days' in summary
        assert 'total_meetings' in summary


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
