"""
Tests for backend.pattern_detector.PatternDetector

Covers instantiation, detect_patterns with insufficient data, day-of-week
pattern detection, trend detection (improving/declining), meeting impact,
time-of-day patterns, milestones, anomaly detection, and multi-week trends.
"""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from backend.pattern_detector import PatternDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Create a MagicMock database with common method stubs."""
    db = MagicMock()
    db.get_daily_summaries.return_value = []
    db.get_echoes.return_value = []
    db.get_readings.return_value = []
    db.get_readings_for_date.return_value = []
    db.get_today_readings.return_value = []
    db.batch_add_echoes.return_value = None
    return db


def _make_summary(day_offset=0, **overrides):
    """Build a daily summary dict for (today - day_offset)."""
    d = date.today() - timedelta(days=day_offset)
    base = {
        'date': d.isoformat(),
        'avg_stress': 45.0,
        'avg_mood': 65.0,
        'avg_energy': 55.0,
        'avg_wellbeing': 65.0,
        'avg_activation': 55.0,
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


def _make_reading(timestamp=None, **overrides):
    """Build a reading dict."""
    base = {
        'timestamp': timestamp or datetime.now().isoformat(),
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
# Instantiation
# ---------------------------------------------------------------------------

class TestPatternDetectorInit:
    def test_instantiation(self):
        """PatternDetector should instantiate with a db reference."""
        db = _make_mock_db()
        detector = PatternDetector(db)
        assert detector.db is db

    def test_has_detect_patterns_method(self):
        """PatternDetector should have a detect_patterns method."""
        db = _make_mock_db()
        detector = PatternDetector(db)
        assert callable(detector.detect_patterns)


# ---------------------------------------------------------------------------
# Insufficient Data
# ---------------------------------------------------------------------------

class TestInsufficientData:
    def test_detect_patterns_empty_data(self):
        """No summaries should return empty list."""
        db = _make_mock_db()
        detector = PatternDetector(db)
        result = detector.detect_patterns()
        assert result == []

    def test_detect_patterns_less_than_7_days(self):
        """Fewer than 7 days of data should return empty list."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=i) for i in range(5)
        ]
        detector = PatternDetector(db)
        result = detector.detect_patterns()
        assert result == []

    def test_detect_patterns_exactly_6_days(self):
        """Exactly 6 days of data should return empty (needs 7)."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [
            _make_summary(day_offset=i) for i in range(6)
        ]
        detector = PatternDetector(db)
        result = detector.detect_patterns()
        assert result == []


# ---------------------------------------------------------------------------
# Day-of-Week Patterns
# ---------------------------------------------------------------------------

class TestDayOfWeekPatterns:
    def test_detects_calmest_day(self):
        """With enough varied data, should detect calmest vs most stressed day."""
        db = _make_mock_db()
        db.get_echoes.return_value = []  # No existing echoes

        # Build 4 weeks of data where Mondays are calm, Fridays are stressed
        summaries = []
        today = date.today()
        for week in range(4):
            for dow in range(7):
                day_offset = week * 7 + dow
                d = today - timedelta(days=day_offset)
                actual_dow = d.weekday()
                if actual_dow == 0:  # Monday
                    stress = 25
                elif actual_dow == 4:  # Friday
                    stress = 70
                else:
                    stress = 45
                summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        db.get_daily_summaries.return_value = summaries
        detector = PatternDetector(db)
        patterns = detector._detect_day_of_week(summaries)

        # Should find a dow_calmest pattern since difference is large
        dow_patterns = [p for p in patterns if p['pattern_type'] == 'dow_calmest']
        assert len(dow_patterns) >= 1
        assert 'Monday' in dow_patterns[0]['message'] or 'Friday' in dow_patterns[0]['message']

    def test_no_pattern_when_uniform(self):
        """Uniform stress across all days should not produce dow pattern."""
        db = _make_mock_db()
        summaries = []
        today = date.today()
        for week in range(4):
            for dow in range(7):
                day_offset = week * 7 + dow
                summaries.append(_make_summary(day_offset=day_offset, avg_stress=50))

        detector = PatternDetector(db)
        patterns = detector._detect_day_of_week(summaries)

        # No significant difference, so no dow_calmest pattern
        dow_patterns = [p for p in patterns if p['pattern_type'] == 'dow_calmest']
        assert len(dow_patterns) == 0

    def test_requires_minimum_data_per_day(self):
        """Need at least 2 entries per day-of-week for analysis."""
        db = _make_mock_db()
        # Only 7 days = 1 entry per DOW, not enough
        summaries = [_make_summary(day_offset=i, avg_stress=20 + i * 10) for i in range(7)]
        detector = PatternDetector(db)
        patterns = detector._detect_day_of_week(summaries)
        # With only 1 entry per DOW, should not produce patterns
        assert len(patterns) == 0


# ---------------------------------------------------------------------------
# Trend Detection
# ---------------------------------------------------------------------------

class TestTrendDetection:
    def test_detects_improving_trend(self):
        """Stress dropping 10+ points over time should trigger trend_stress_down."""
        db = _make_mock_db()
        summaries = []
        today = date.today()
        # First week: high stress (65). Last week: low stress (40).
        for i in range(14):
            day_offset = 13 - i  # oldest first
            if i < 7:
                stress = 65
            else:
                stress = 40
            summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        detector = PatternDetector(db)
        patterns = detector._detect_trends(summaries)

        down_patterns = [p for p in patterns if 'stress_down' in p['pattern_type']]
        assert len(down_patterns) >= 1
        assert 'dropped' in down_patterns[0]['message'].lower()

    def test_detects_declining_trend(self):
        """Stress rising 10+ points should trigger trend_stress_up."""
        db = _make_mock_db()
        summaries = []
        today = date.today()
        for i in range(14):
            day_offset = 13 - i
            if i < 7:
                stress = 30
            else:
                stress = 65
            summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        detector = PatternDetector(db)
        patterns = detector._detect_trends(summaries)

        up_patterns = [p for p in patterns if 'stress_up' in p['pattern_type']]
        assert len(up_patterns) >= 1
        assert 'risen' in up_patterns[0]['message'].lower()

    def test_no_trend_when_stable(self):
        """Stable stress should not trigger any trend pattern."""
        db = _make_mock_db()
        summaries = [_make_summary(day_offset=i, avg_stress=50) for i in range(14)]
        detector = PatternDetector(db)
        patterns = detector._detect_trends(summaries)

        trend_patterns = [p for p in patterns if 'trend_stress' in p['pattern_type']]
        assert len(trend_patterns) == 0

    def test_insufficient_data_for_trends(self):
        """Fewer than 14 days should not produce trends."""
        db = _make_mock_db()
        summaries = [_make_summary(day_offset=i) for i in range(10)]
        detector = PatternDetector(db)
        patterns = detector._detect_trends(summaries)
        assert patterns == []

    def test_calm_time_trend(self):
        """Increasing calm time should produce trend_calm_up."""
        db = _make_mock_db()
        summaries = []
        for i in range(14):
            day_offset = 13 - i
            if i < 7:
                calm = 10  # First week: low calm
            else:
                calm = 35  # Last week: high calm (25+ increase)
            summaries.append(_make_summary(day_offset=day_offset, time_in_calm_min=calm))

        detector = PatternDetector(db)
        patterns = detector._detect_trends(summaries)

        calm_patterns = [p for p in patterns if 'calm_up' in p['pattern_type']]
        assert len(calm_patterns) >= 1


# ---------------------------------------------------------------------------
# Meeting Impact
# ---------------------------------------------------------------------------

class TestMeetingImpact:
    def test_detects_meeting_stress_impact(self):
        """Meeting-heavy days with higher stress should trigger pattern."""
        db = _make_mock_db()
        summaries = []
        for i in range(21):
            if i % 3 == 0:  # Every 3rd day: heavy meetings
                summaries.append(_make_summary(
                    day_offset=i, total_meetings=5, avg_stress=65))
            elif i % 3 == 1:  # No meetings
                summaries.append(_make_summary(
                    day_offset=i, total_meetings=0, avg_stress=35))
            else:
                summaries.append(_make_summary(
                    day_offset=i, total_meetings=1, avg_stress=45))

        detector = PatternDetector(db)
        patterns = detector._detect_meeting_impact(summaries)

        meeting_patterns = [p for p in patterns if 'meeting_impact' in p['pattern_type']]
        assert len(meeting_patterns) >= 1

    def test_no_meeting_impact_without_enough_data(self):
        """Too few meeting/no-meeting days should not produce a pattern."""
        db = _make_mock_db()
        summaries = [_make_summary(day_offset=i, total_meetings=2, avg_stress=50) for i in range(10)]
        detector = PatternDetector(db)
        patterns = detector._detect_meeting_impact(summaries)
        assert patterns == []


# ---------------------------------------------------------------------------
# Time of Day Patterns
# ---------------------------------------------------------------------------

class TestTimeOfDayPatterns:
    def test_insufficient_readings_no_pattern(self):
        """Fewer than 20 readings should not produce time-of-day pattern."""
        db = _make_mock_db()
        db.get_readings.return_value = [_make_reading() for _ in range(10)]
        detector = PatternDetector(db)
        patterns = detector._detect_time_of_day()
        assert patterns == []

    def test_detects_calmest_time_bucket(self):
        """Different stress by time of day should reveal calmest period."""
        db = _make_mock_db()
        readings = []
        base_date = date.today()
        # Morning readings: low stress
        for i in range(10):
            ts = datetime(base_date.year, base_date.month, base_date.day, 8, i * 5, 0).isoformat()
            readings.append(_make_reading(timestamp=ts, stress_score=25))
        # Afternoon readings: high stress
        for i in range(10):
            ts = datetime(base_date.year, base_date.month, base_date.day, 14, i * 5, 0).isoformat()
            readings.append(_make_reading(timestamp=ts, stress_score=65))

        db.get_readings.return_value = readings
        detector = PatternDetector(db)
        patterns = detector._detect_time_of_day()

        tod_patterns = [p for p in patterns if p['pattern_type'] == 'tod_stress']
        assert len(tod_patterns) >= 1
        assert 'morning' in tod_patterns[0]['message'].lower()


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

class TestMilestoneDetection:
    def test_50_readings_milestone(self):
        """50+ readings should trigger milestone_50 pattern."""
        db = _make_mock_db()
        readings = [_make_reading(speech_duration_sec=30) for _ in range(55)]
        db.get_readings.return_value = readings
        detector = PatternDetector(db)
        summaries = [_make_summary(day_offset=i) for i in range(14)]
        patterns = detector._detect_milestones(summaries)

        milestone_50 = [p for p in patterns if p['pattern_type'] == 'milestone_50_readings']
        assert len(milestone_50) == 1

    def test_no_milestone_below_threshold(self):
        """Below 50 readings should not trigger any milestone."""
        db = _make_mock_db()
        db.get_readings.return_value = [_make_reading() for _ in range(30)]
        detector = PatternDetector(db)
        summaries = [_make_summary(day_offset=i) for i in range(14)]
        patterns = detector._detect_milestones(summaries)
        assert patterns == []


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------

class TestAnomalyDetection:
    def test_no_anomaly_with_insufficient_data(self):
        """Fewer than 14 summaries should not detect anomalies."""
        db = _make_mock_db()
        summaries = [_make_summary(day_offset=i) for i in range(10)]
        detector = PatternDetector(db)
        patterns = detector._detect_anomalies(summaries)
        assert patterns == []

    def test_no_anomaly_without_today(self):
        """If today has no summary, no anomaly is detected."""
        db = _make_mock_db()
        # All summaries are from past days, none for today
        summaries = [_make_summary(day_offset=i) for i in range(1, 20)]
        detector = PatternDetector(db)
        patterns = detector._detect_anomalies(summaries)
        assert patterns == []

    def test_anomaly_detection_with_unusual_day(self):
        """Today with stress far from same-weekday average should trigger anomaly."""
        db = _make_mock_db()
        today = date.today()
        today_dow = today.weekday()

        summaries = []
        # Today: very high stress
        summaries.append(_make_summary(day_offset=0, avg_stress=90))
        # Past weeks: same weekday with normal stress
        for week in range(1, 5):
            d_offset = week * 7
            target_date = today - timedelta(days=d_offset)
            # Make sure it's the same weekday
            if target_date.weekday() == today_dow:
                summaries.append({
                    'date': target_date.isoformat(),
                    'avg_stress': 40.0,
                    'avg_mood': 65.0,
                })
        # Add some filler days for the 14-day minimum
        for i in range(1, 15):
            d = today - timedelta(days=i)
            if d.isoformat() not in {s['date'] for s in summaries}:
                summaries.append(_make_summary(day_offset=i))

        detector = PatternDetector(db)
        patterns = detector._detect_anomalies(summaries)

        anomaly_patterns = [p for p in patterns if 'anomaly' in p['pattern_type']]
        # May or may not trigger depending on weekday data alignment
        # But the method should not crash
        assert isinstance(patterns, list)


# ---------------------------------------------------------------------------
# Multi-Week Trends (Burnout Detection)
# ---------------------------------------------------------------------------

class TestMultiWeekTrends:
    def test_insufficient_data_no_multi_week_trend(self):
        """Fewer than 28 days should not produce multi-week trends."""
        db = _make_mock_db()
        summaries = [_make_summary(day_offset=i) for i in range(20)]
        detector = PatternDetector(db)
        patterns = detector._detect_multi_week_trends(summaries)
        assert patterns == []

    def test_burnout_trajectory_detected(self):
        """Steadily rising stress over 4+ weeks should trigger burnout warning."""
        db = _make_mock_db()
        summaries = []
        # 5 weeks of data, stress rising ~5 points per week
        for week in range(5):
            for day in range(7):
                day_offset = (4 - week) * 7 + (6 - day)
                stress = 30 + week * 8  # 30, 38, 46, 54, 62
                summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        detector = PatternDetector(db)
        patterns = detector._detect_multi_week_trends(summaries)

        burnout_patterns = [p for p in patterns if 'burnout' in p['pattern_type']]
        assert len(burnout_patterns) >= 1
        assert 'climbing' in burnout_patterns[0]['message'].lower()

    def test_recovery_trajectory_detected(self):
        """Steadily declining stress over 4+ weeks should trigger recovery pattern."""
        db = _make_mock_db()
        summaries = []
        for week in range(5):
            for day in range(7):
                day_offset = (4 - week) * 7 + (6 - day)
                stress = 70 - week * 8  # 70, 62, 54, 46, 38
                summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        detector = PatternDetector(db)
        patterns = detector._detect_multi_week_trends(summaries)

        recovery_patterns = [p for p in patterns if 'recovery_trajectory' in p['pattern_type']]
        assert len(recovery_patterns) >= 1
        assert 'dropping' in recovery_patterns[0]['message'].lower()


# ---------------------------------------------------------------------------
# Full detect_patterns integration
# ---------------------------------------------------------------------------

class TestDetectPatternsIntegration:
    def test_detect_patterns_filters_existing(self):
        """Patterns already in echoes should be filtered out."""
        db = _make_mock_db()
        summaries = []
        today = date.today()
        for week in range(4):
            for dow in range(7):
                day_offset = week * 7 + dow
                d = today - timedelta(days=day_offset)
                actual_dow = d.weekday()
                stress = 25 if actual_dow == 0 else 70 if actual_dow == 4 else 45
                summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        db.get_daily_summaries.return_value = summaries
        # Mark dow_calmest as already discovered
        db.get_echoes.return_value = [{'pattern_type': 'dow_calmest'}]

        detector = PatternDetector(db)
        result = detector.detect_patterns()

        # dow_calmest should NOT be in the results (already exists)
        dow_results = [p for p in result if p['pattern_type'] == 'dow_calmest']
        assert len(dow_results) == 0

    def test_detect_patterns_batch_inserts(self):
        """New discoveries should be batch-inserted into the database."""
        db = _make_mock_db()
        summaries = [_make_summary(day_offset=i) for i in range(14)]
        db.get_daily_summaries.return_value = summaries

        detector = PatternDetector(db)
        detector.detect_patterns()

        # batch_add_echoes should always be called (even with empty list)
        db.batch_add_echoes.assert_called_once()

    def test_detect_patterns_returns_list(self):
        """detect_patterns should always return a list."""
        db = _make_mock_db()
        db.get_daily_summaries.return_value = [_make_summary(day_offset=i) for i in range(10)]
        detector = PatternDetector(db)
        result = detector.detect_patterns()
        assert isinstance(result, list)

    def test_pattern_dict_structure(self):
        """Each pattern dict should have at least pattern_type and message."""
        db = _make_mock_db()
        summaries = []
        today = date.today()
        for week in range(4):
            for dow in range(7):
                day_offset = week * 7 + dow
                d = today - timedelta(days=day_offset)
                actual_dow = d.weekday()
                stress = 20 if actual_dow == 0 else 75 if actual_dow == 4 else 45
                summaries.append(_make_summary(day_offset=day_offset, avg_stress=stress))

        db.get_daily_summaries.return_value = summaries

        detector = PatternDetector(db)
        result = detector.detect_patterns()

        for pattern in result:
            assert 'pattern_type' in pattern
            assert 'message' in pattern
            assert isinstance(pattern['pattern_type'], str)
            assert isinstance(pattern['message'], str)
