"""
Tests for backend.insight_engine.InsightEngine

Covers instantiation, wellness score computation, compass direction,
cache behavior, generate_insight with various reading states,
morning briefing, evening recap, and first reading interpretation.
"""
import asyncio
import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.insight_engine import InsightEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_summary(**overrides):
    """Build a daily summary dict with sensible defaults."""
    base = {
        'date': date.today().isoformat(),
        'avg_stress': 45.0,
        'avg_wellbeing': 65.0,
        'avg_mood': 65.0,
        'avg_activation': 55.0,
        'avg_energy': 55.0,
        'avg_calm': 60.0,
        'avg_depression_risk': 15.0,
        'avg_anxiety_risk': 12.0,
        'avg_emotional_stability': 75.0,
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
    """Build a reading dict with sensible defaults."""
    from datetime import datetime
    base = {
        'timestamp': datetime.now().isoformat(),
        'stress_score': 45.0,
        'wellbeing_score': 65.0,
        'mood_score': 65.0,
        'activation_score': 55.0,
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

class TestInsightEngineInit:
    def test_instantiation(self):
        """InsightEngine should instantiate with empty cache."""
        engine = InsightEngine()
        assert engine._cache is None
        assert engine._cache_time == 0
        assert engine._cache_ttl == 60

    def test_default_cache_ttl(self):
        """Default cache TTL is 60 seconds."""
        engine = InsightEngine()
        assert engine._cache_ttl == 60


# ---------------------------------------------------------------------------
# generate_insight
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    """Disable Ollama so tests always use deterministic template fallback."""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(InsightEngine, '_ollama_generate', _noop)


class TestGenerateInsight:
    def test_no_readings_returns_prompt(self):
        """With no readings, insight should prompt user to start."""
        engine = InsightEngine()
        result = _run_async(engine.generate_insight([], None, {}))
        assert result['success'] is True
        assert 'No readings yet today' in result['insight']
        assert result['cached'] is False

    def test_one_reading_returns_zone_observation(self):
        """With one reading, insight should include zone-based text."""
        engine = InsightEngine()
        reading = _make_reading(zone='calm', stress_score=25.0)
        result = _run_async(engine.generate_insight([reading], None, {}))
        assert result['success'] is True
        assert 'calm zone' in result['insight']
        assert result['cached'] is False

    def test_stressed_zone_shows_tension(self):
        """Stressed zone reading should produce tension/stress message."""
        engine = InsightEngine()
        reading = _make_reading(zone='stressed', stress_score=75.0)
        result = _run_async(engine.generate_insight([reading], None, {}))
        assert result['success'] is True
        assert 'elevated' in result['insight'].lower() or 'stress' in result['insight'].lower()

    def test_tense_zone_suggests_break(self):
        """Tense zone reading should suggest a break."""
        engine = InsightEngine()
        reading = _make_reading(zone='tense', stress_score=60.0)
        result = _run_async(engine.generate_insight([reading], None, {}))
        assert result['success'] is True
        text = result['insight'].lower()
        assert any(w in text for w in ('tension', 'break', 'stress', 'tense', 'breathing', 'relax'))

    def test_multiple_readings_include_count(self):
        """With multiple readings, the insight may reference the reading count."""
        engine = InsightEngine()
        readings = [_make_reading(zone='steady') for _ in range(5)]
        summary = _make_summary(time_in_calm_min=25, time_in_stressed_min=5)
        result = _run_async(engine.generate_insight(readings, summary, {}))
        assert result['success'] is True
        assert len(result['insight']) > 0


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

class TestInsightCache:
    def test_second_call_returns_cached(self):
        """A second call within TTL should return the cached insight."""
        engine = InsightEngine()
        reading = _make_reading(zone='calm', stress_score=20.0)

        result1 = _run_async(engine.generate_insight([reading], None, {}))
        assert result1['cached'] is False

        result2 = _run_async(engine.generate_insight([reading], None, {}))
        assert result2['cached'] is True
        assert result2['insight'] == result1['insight']

    def test_cache_expires_after_ttl(self):
        """After TTL expires, the next call should regenerate."""
        engine = InsightEngine()
        engine._cache_ttl = 0.1  # 100ms for fast test
        reading = _make_reading(zone='steady')

        result1 = _run_async(engine.generate_insight([reading], None, {}))
        assert result1['cached'] is False

        time.sleep(0.15)  # Wait past TTL

        result2 = _run_async(engine.generate_insight([reading], None, {}))
        assert result2['cached'] is False

    def test_cache_stores_insight_string(self):
        """Cache stores the insight string internally."""
        engine = InsightEngine()
        reading = _make_reading(zone='calm', stress_score=20.0)
        _run_async(engine.generate_insight([reading], None, {}))
        assert engine._cache is not None
        assert isinstance(engine._cache, str)


# ---------------------------------------------------------------------------
# Wellness Score Computation
# ---------------------------------------------------------------------------

class TestWellnessScore:
    def test_wellness_with_no_summary(self):
        """No summary data should return score 0 with has_data=False."""
        engine = InsightEngine()
        db = MagicMock()
        result = engine.compute_wellness_score(db, None)
        assert result['score'] == 0
        assert result['has_data'] is False

    def test_wellness_with_valid_summary(self):
        """A valid summary should produce a score between 0 and 100."""
        engine = InsightEngine()
        db = MagicMock()
        summary = _make_summary()
        result = engine.compute_wellness_score(db, summary)
        assert result['has_data'] is True
        assert 0 <= result['score'] <= 100
        assert result['profile'] == 'Daily Wellness'
        db.set_wellness_score.assert_called_once()

    def test_wellness_low_stress_high_wellbeing_scores_high(self):
        """Low stress + high wellbeing + high calm should yield high wellness score."""
        engine = InsightEngine()
        db = MagicMock()
        summary = _make_summary(
            avg_stress=10,
            avg_wellbeing=90,
            avg_activation=80,
            avg_calm=90,
            avg_depression_risk=5,
            avg_anxiety_risk=5,
            avg_emotional_stability=95,
            time_in_calm_min=60,
            time_in_steady_min=20,
            time_in_tense_min=0,
            time_in_stressed_min=0,
        )
        result = engine.compute_wellness_score(db, summary)
        assert result['score'] >= 80

    def test_wellness_high_stress_low_wellbeing_scores_low(self):
        """High stress + low wellbeing should yield low wellness score."""
        engine = InsightEngine()
        db = MagicMock()
        summary = _make_summary(
            avg_stress=85,
            avg_wellbeing=20,
            avg_activation=25,
            avg_calm=15,
            avg_depression_risk=70,
            avg_anxiety_risk=65,
            avg_emotional_stability=20,
            time_in_calm_min=0,
            time_in_steady_min=5,
            time_in_tense_min=30,
            time_in_stressed_min=60,
        )
        result = engine.compute_wellness_score(db, summary)
        assert result['score'] <= 45

    def test_wellness_stores_in_db(self):
        """Wellness score should be stored via db.set_wellness_score."""
        engine = InsightEngine()
        db = MagicMock()
        summary = _make_summary()
        result = engine.compute_wellness_score(db, summary)
        db.set_wellness_score.assert_called_once()
        args = db.set_wellness_score.call_args[0]
        assert args[0] == date.today().isoformat()
        assert args[1] == result['score']

    def test_wellness_missing_new_scores_redistributes(self):
        """Missing depression/anxiety/stability scores should still produce valid result."""
        engine = InsightEngine()
        db = MagicMock()
        summary = _make_summary()
        # Remove the newer scores
        del summary['avg_depression_risk']
        del summary['avg_anxiety_risk']
        del summary['avg_emotional_stability']
        result = engine.compute_wellness_score(db, summary)
        assert result['has_data'] is True
        assert 0 <= result['score'] <= 100


# ---------------------------------------------------------------------------
# Intraday Wellness Score
# ---------------------------------------------------------------------------

class TestIntradayWellness:
    def test_intraday_insufficient_readings(self):
        """Zero readings returns has_data=False with needed count."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_today_readings.return_value = []
        result = engine.compute_intraday_wellness_score(db)
        assert result['has_data'] is False
        assert result['readings_needed'] == 1

    def test_intraday_with_enough_readings(self):
        """3+ readings and a valid summary should produce a score."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_today_readings.return_value = [_make_reading() for _ in range(5)]
        db.compute_daily_summary.return_value = _make_summary()
        result = engine.compute_intraday_wellness_score(db)
        assert result['has_data'] is True
        assert 0 <= result['score'] <= 100
        assert result['reading_count'] == 5

    def test_intraday_no_summary(self):
        """If compute_daily_summary returns None, has_data is False."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_today_readings.return_value = [_make_reading() for _ in range(5)]
        db.compute_daily_summary.return_value = None
        result = engine.compute_intraday_wellness_score(db)
        assert result['has_data'] is False


# ---------------------------------------------------------------------------
# Compass
# ---------------------------------------------------------------------------

class TestCompass:
    def test_compass_insufficient_data(self):
        """Fewer than 7 summaries should return holding with no data."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_compass_entry.return_value = None
        db.get_daily_summaries.return_value = [_make_summary() for _ in range(3)]
        result = engine.compute_compass(db)
        assert result['direction'] == 'holding'
        assert result['has_data'] is False

    def test_compass_returns_cached_entry(self):
        """If a compass entry already exists for this week, return it."""
        engine = InsightEngine()
        db = MagicMock()
        cached = {'direction': 'ascending', 'has_data': True}
        db.get_compass_entry.return_value = cached
        result = engine.compute_compass(db)
        assert result == cached

    def test_compass_ascending_direction(self):
        """Stress decreasing + wellbeing increasing should give ascending."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_compass_entry.return_value = None

        # Build 14 summaries: last week high stress, this week low stress
        summaries = []
        today = date.today()
        for i in range(14):
            d = today - timedelta(days=i)
            if i < 7:  # this week: low stress, high wellbeing
                s = _make_summary(date=d.isoformat(), avg_stress=25, avg_wellbeing=80,
                                  avg_activation=70, avg_calm=75)
            else:  # last week: high stress, low wellbeing
                s = _make_summary(date=d.isoformat(), avg_stress=65, avg_wellbeing=40,
                                  avg_activation=35, avg_calm=30)
            summaries.append(s)

        db.get_daily_summaries.return_value = summaries
        result = engine.compute_compass(db)
        assert result['has_data'] is True
        assert result['direction'] == 'ascending'
        db.upsert_compass.assert_called_once()

    def test_compass_descending_direction(self):
        """Stress increasing + wellbeing decreasing should give descending."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_compass_entry.return_value = None

        summaries = []
        today = date.today()
        for i in range(14):
            d = today - timedelta(days=i)
            if i < 7:  # this week: high stress, low wellbeing
                s = _make_summary(date=d.isoformat(), avg_stress=70, avg_wellbeing=30,
                                  avg_activation=30, avg_calm=20)
            else:  # last week: low stress, high wellbeing
                s = _make_summary(date=d.isoformat(), avg_stress=25, avg_wellbeing=80,
                                  avg_activation=70, avg_calm=75)
            summaries.append(s)

        db.get_daily_summaries.return_value = summaries
        result = engine.compute_compass(db)
        assert result['has_data'] is True
        assert result['direction'] == 'descending'

    def test_compass_holding_when_stable(self):
        """Similar metrics across weeks should give holding."""
        engine = InsightEngine()
        db = MagicMock()
        db.get_compass_entry.return_value = None

        summaries = []
        today = date.today()
        for i in range(14):
            d = today - timedelta(days=i)
            s = _make_summary(date=d.isoformat(), avg_stress=50, avg_wellbeing=55,
                              avg_activation=50, avg_calm=50)
            summaries.append(s)

        db.get_daily_summaries.return_value = summaries
        result = engine.compute_compass(db)
        assert result['has_data'] is True
        assert result['direction'] == 'holding'


# ---------------------------------------------------------------------------
# Interpret First Reading
# ---------------------------------------------------------------------------

class TestInterpretFirstReading:
    def test_low_stress_reading(self):
        """Low stress reading should show 'low' in narrative."""
        engine = InsightEngine()
        reading = _make_reading(stress_score=20.0, activation_score=70.0)
        result = engine.interpret_first_reading(reading)
        assert 'low stress' in result['narrative']
        assert result['stress_percentile'] > 50  # Lower than most

    def test_high_stress_reading(self):
        """High stress reading should show 'high' in narrative."""
        engine = InsightEngine()
        reading = _make_reading(stress_score=80.0, activation_score=30.0)
        result = engine.interpret_first_reading(reading)
        assert 'high' in result['narrative']
        assert result['stress_percentile'] < 30

    def test_result_structure(self):
        """Result should have narrative, percentile, percentile_text, and unlocks."""
        engine = InsightEngine()
        reading = _make_reading()
        result = engine.interpret_first_reading(reading)
        assert 'narrative' in result
        assert 'stress_percentile' in result
        assert 'percentile_text' in result
        assert 'unlocks' in result
        assert len(result['unlocks']) == 4

    def test_unlocks_have_expected_milestones(self):
        """Unlocks should include days 3, 7, 14, and 30."""
        engine = InsightEngine()
        result = engine.interpret_first_reading(_make_reading())
        days = [u['day'] for u in result['unlocks']]
        assert days == [3, 7, 14, 30]


# ---------------------------------------------------------------------------
# Morning Briefing
# ---------------------------------------------------------------------------

class TestMorningBriefing:
    def test_no_data_returns_has_data_false(self):
        """Empty summary/readings returns has_data=False."""
        engine = InsightEngine()
        result = _run_async(engine.generate_morning_briefing('2025-01-01', [], None))
        assert result['has_data'] is False

    def test_valid_data_returns_structured_briefing(self):
        """A valid summary + readings returns rich structured briefing."""
        engine = InsightEngine()
        from datetime import datetime
        readings = [
            _make_reading(timestamp=(datetime.now() - timedelta(hours=8)).isoformat()),
            _make_reading(timestamp=(datetime.now() - timedelta(hours=4)).isoformat()),
            _make_reading(timestamp=(datetime.now() - timedelta(hours=1)).isoformat()),
        ]
        summary = _make_summary()
        result = _run_async(engine.generate_morning_briefing('2025-01-20', readings, summary))
        assert result['has_data'] is True
        assert 'overall_score' in result
        assert 0 <= result['overall_score'] <= 100
        assert result['score_label'] in ('Optimal', 'Good', 'Fair', 'Needs Attention')
        assert 'metrics' in result
        assert 'zones' in result
        assert 'activity' in result
        assert 'highlights' in result
        assert 'coach_note' in result
        assert len(result['coach_note']) > 0


# ---------------------------------------------------------------------------
# Evening Recap
# ---------------------------------------------------------------------------

class TestEveningRecap:
    def test_no_data_returns_fallback(self):
        """No summary/readings returns fallback message."""
        engine = InsightEngine()
        result = _run_async(engine.generate_evening_recap(None, []))
        assert 'just beginning' in result.lower() or 'check back' in result.lower()

    def test_valid_data_returns_recap(self):
        """Valid data returns a non-empty recap string."""
        engine = InsightEngine()
        from datetime import datetime
        readings = [
            _make_reading(
                timestamp=datetime.now().isoformat(),
                stress_score=40.0,
            ),
        ]
        summary = _make_summary(avg_stress=40, peak_stress=60, time_in_calm_min=25)
        result = _run_async(engine.generate_evening_recap(summary, readings))
        assert len(result) > 0
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _compute_wellness_components edge cases
# ---------------------------------------------------------------------------

class TestWellnessComponents:
    def test_all_zeros_summary(self):
        """All zero metrics should produce a valid score."""
        engine = InsightEngine()
        summary = _make_summary(
            avg_stress=0, avg_wellbeing=0, avg_activation=0, avg_calm=0,
            avg_depression_risk=0, avg_anxiety_risk=0, avg_emotional_stability=0,
            time_in_calm_min=0, time_in_steady_min=0,
            time_in_tense_min=0, time_in_stressed_min=0,
        )
        score = engine._compute_wellness_components(summary)
        assert 0 <= score <= 100

    def test_perfect_metrics_high_score(self):
        """Perfect metrics (low stress, high everything else) should yield near-100."""
        engine = InsightEngine()
        summary = _make_summary(
            avg_stress=0, avg_wellbeing=100, avg_activation=100, avg_calm=100,
            avg_depression_risk=0, avg_anxiety_risk=0, avg_emotional_stability=100,
            time_in_calm_min=100, time_in_steady_min=0,
            time_in_tense_min=0, time_in_stressed_min=0,
        )
        score = engine._compute_wellness_components(summary)
        assert score >= 95

    def test_score_bounded_0_100(self):
        """Score should always be between 0 and 100 regardless of input."""
        engine = InsightEngine()
        # Extreme worst case
        summary = _make_summary(
            avg_stress=100, avg_wellbeing=0, avg_activation=0, avg_calm=0,
            avg_depression_risk=100, avg_anxiety_risk=100, avg_emotional_stability=0,
            time_in_calm_min=0, time_in_steady_min=0,
            time_in_tense_min=0, time_in_stressed_min=100,
        )
        score = engine._compute_wellness_components(summary)
        assert 0 <= score <= 100
