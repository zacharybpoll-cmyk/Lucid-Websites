"""
Tests for backend.database.Database

Covers CRUD operations on readings, daily summaries, echoes, baselines,
tags, speaker profiles, and concurrent access safety.
"""
import threading
import time
from datetime import datetime, date, timedelta

import pytest


# ---------------------------------------------------------------------------
# Reading CRUD
# ---------------------------------------------------------------------------

class TestReadingsCRUD:
    def test_add_and_get_reading(self, temp_db, sample_reading):
        """Insert a reading and retrieve it — verify all fields round-trip."""
        row_id = temp_db.insert_reading(sample_reading)
        assert row_id >= 1

        readings = temp_db.get_readings(limit=1)
        assert len(readings) == 1

        r = readings[0]
        assert r['id'] == row_id
        assert r['timestamp'] == sample_reading['timestamp']
        assert r['depression_raw'] == pytest.approx(sample_reading['depression_raw'])
        assert r['anxiety_raw'] == pytest.approx(sample_reading['anxiety_raw'])
        assert r['depression_quantized'] == sample_reading['depression_quantized']
        assert r['anxiety_quantized'] == sample_reading['anxiety_quantized']
        assert r['depression_mapped'] == pytest.approx(sample_reading['depression_mapped'])
        assert r['anxiety_mapped'] == pytest.approx(sample_reading['anxiety_mapped'])
        assert r['f0_mean'] == pytest.approx(sample_reading['f0_mean'])
        assert r['f0_std'] == pytest.approx(sample_reading['f0_std'])
        assert r['speech_rate'] == pytest.approx(sample_reading['speech_rate'])
        assert r['rms_energy'] == pytest.approx(sample_reading['rms_energy'])
        assert r['spectral_centroid'] == pytest.approx(sample_reading['spectral_centroid'])
        assert r['spectral_entropy'] == pytest.approx(sample_reading['spectral_entropy'])
        assert r['zcr'] == pytest.approx(sample_reading['zcr'])
        assert r['jitter'] == pytest.approx(sample_reading['jitter'])
        assert r['shimmer'] == pytest.approx(sample_reading['shimmer'])
        assert r['voice_breaks'] == sample_reading['voice_breaks']
        assert r['stress_score'] == pytest.approx(sample_reading['stress_score'])
        assert r['mood_score'] == pytest.approx(sample_reading['mood_score'])
        assert r['energy_score'] == pytest.approx(sample_reading['energy_score'])
        assert r['calm_score'] == pytest.approx(sample_reading['calm_score'])
        assert r['zone'] == sample_reading['zone']
        assert r['speech_duration_sec'] == pytest.approx(sample_reading['speech_duration_sec'])
        assert r['meeting_detected'] == sample_reading['meeting_detected']
        assert r['speaker_verified'] == sample_reading['speaker_verified']
        assert r['speaker_similarity'] == pytest.approx(sample_reading['speaker_similarity'])

    def test_get_readings_by_date(self, temp_db, sample_reading):
        """Insert readings across two dates and query by date range."""
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        # Insert one reading for yesterday
        reading_yesterday = dict(sample_reading)
        reading_yesterday['timestamp'] = yesterday.isoformat()
        reading_yesterday['stress_score'] = 70.0
        temp_db.insert_reading(reading_yesterday)

        # Insert one reading for today
        reading_today = dict(sample_reading)
        reading_today['timestamp'] = now.isoformat()
        reading_today['stress_score'] = 30.0
        temp_db.insert_reading(reading_today)

        # Query only today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
        today_readings = temp_db.get_readings(start_time=today_start, end_time=today_end)

        assert len(today_readings) == 1
        assert today_readings[0]['stress_score'] == pytest.approx(30.0)

        # Query only yesterday
        yest_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        yest_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
        yest_readings = temp_db.get_readings(start_time=yest_start, end_time=yest_end)

        assert len(yest_readings) == 1
        assert yest_readings[0]['stress_score'] == pytest.approx(70.0)

    def test_get_readings_limit(self, temp_db, sample_reading):
        """Verify the limit parameter caps the result set."""
        for i in range(5):
            r = dict(sample_reading)
            r['timestamp'] = (datetime.now() + timedelta(seconds=i)).isoformat()
            temp_db.insert_reading(r)

        all_readings = temp_db.get_readings(limit=100)
        assert len(all_readings) == 5

        limited = temp_db.get_readings(limit=3)
        assert len(limited) == 3

    def test_get_readings_returns_desc_order(self, temp_db, sample_reading):
        """Readings should be returned in descending timestamp order."""
        for i in range(3):
            r = dict(sample_reading)
            ts = (datetime.now() + timedelta(minutes=i)).isoformat()
            r['timestamp'] = ts
            temp_db.insert_reading(r)

        readings = temp_db.get_readings(limit=10)
        timestamps = [r['timestamp'] for r in readings]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_insert_reading_returns_autoincrement_id(self, temp_db, sample_reading):
        """Each insert returns a unique, monotonically increasing ID."""
        id1 = temp_db.insert_reading(sample_reading)
        id2 = temp_db.insert_reading(sample_reading)
        assert id2 == id1 + 1

    def test_get_readings_with_none_fields(self, temp_db):
        """Insert a minimal reading with many None fields."""
        minimal = {
            'timestamp': datetime.now().isoformat(),
            'stress_score': 50.0,
            'mood_score': 50.0,
            'energy_score': 50.0,
            'calm_score': 50.0,
            'zone': 'steady',
            'speech_duration_sec': 30.0,
        }
        row_id = temp_db.insert_reading(minimal)
        readings = temp_db.get_readings(limit=1)
        assert readings[0]['id'] == row_id
        assert readings[0]['f0_mean'] is None
        assert readings[0]['jitter'] is None


# ---------------------------------------------------------------------------
# Daily Summaries
# ---------------------------------------------------------------------------

class TestDailySummary:
    def test_daily_summary_with_no_readings(self, temp_db):
        """compute_daily_summary with no readings returns empty dict."""
        summary = temp_db.compute_daily_summary(target_date=date.today())
        assert summary == {}

    def test_daily_summary_aggregation(self, temp_db, sample_reading):
        """Insert multiple readings for today and verify averages and zone minutes."""
        now = datetime.now()

        # 3 readings: stressed, tense, calm
        zones_scores = [
            ('stressed', 80.0, 40.0, 50.0, 30.0, 60.0),
            ('tense', 55.0, 60.0, 65.0, 50.0, 45.0),
            ('calm', 20.0, 80.0, 70.0, 85.0, 30.0),
        ]

        for i, (zone, stress, mood, energy, calm, speech_dur) in enumerate(zones_scores):
            r = dict(sample_reading)
            r['timestamp'] = (now + timedelta(seconds=i)).isoformat()
            r['zone'] = zone
            r['stress_score'] = stress
            r['mood_score'] = mood
            r['energy_score'] = energy
            r['calm_score'] = calm
            r['speech_duration_sec'] = speech_dur
            r['meeting_detected'] = 0
            temp_db.insert_reading(r)

        summary = temp_db.compute_daily_summary(target_date=date.today())

        assert summary['date'] == date.today().isoformat()
        assert summary['avg_stress'] == pytest.approx((80 + 55 + 20) / 3, rel=1e-2)
        assert summary['avg_mood'] == pytest.approx((40 + 60 + 80) / 3, rel=1e-2)
        assert summary['avg_energy'] == pytest.approx((50 + 65 + 70) / 3, rel=1e-2)
        assert summary['avg_calm'] == pytest.approx((30 + 50 + 85) / 3, rel=1e-2)
        assert summary['peak_stress'] == pytest.approx(80.0)

        # Zone time: each reading counts as 5 min
        assert summary['time_in_stressed_min'] == pytest.approx(5.0)
        assert summary['time_in_tense_min'] == pytest.approx(5.0)
        assert summary['time_in_calm_min'] == pytest.approx(5.0)
        assert summary['time_in_steady_min'] == pytest.approx(0.0)

        # Total speech
        assert summary['total_speech_min'] == pytest.approx((60 + 45 + 30) / 60, rel=1e-2)

    def test_daily_summary_stored_and_retrievable(self, temp_db, sample_reading):
        """compute_daily_summary stores the result; get_summary_for_date retrieves it."""
        r = dict(sample_reading)
        r['timestamp'] = datetime.now().isoformat()
        temp_db.insert_reading(r)

        summary = temp_db.compute_daily_summary(target_date=date.today())
        assert summary != {}

        stored = temp_db.get_summary_for_date(date.today())
        assert stored is not None
        assert stored['date'] == date.today().isoformat()
        assert stored['avg_stress'] == pytest.approx(summary['avg_stress'])

    def test_get_daily_summaries(self, temp_db, sample_reading):
        """get_daily_summaries returns summaries within the window."""
        # Create readings for 3 days
        for day_offset in range(3):
            target_date = date.today() - timedelta(days=day_offset)
            r = dict(sample_reading)
            ts = datetime.combine(target_date, datetime.min.time().replace(hour=12))
            r['timestamp'] = ts.isoformat()
            temp_db.insert_reading(r)
            temp_db.compute_daily_summary(target_date=target_date)

        summaries = temp_db.get_daily_summaries(days=14)
        assert len(summaries) == 3
        # Most recent first
        dates = [s['date'] for s in summaries]
        assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Concurrent Access
# ---------------------------------------------------------------------------

class TestConcurrentAccess:
    def test_concurrent_inserts(self, temp_db, sample_reading):
        """10 threads each insert 10 readings concurrently without errors."""
        errors = []

        def insert_batch(thread_id):
            try:
                for i in range(10):
                    r = dict(sample_reading)
                    r['timestamp'] = (
                        datetime.now() + timedelta(seconds=thread_id * 100 + i)
                    ).isoformat()
                    r['stress_score'] = float(thread_id * 10 + i)
                    temp_db.insert_reading(r)
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=insert_batch, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"Errors during concurrent inserts: {errors}"

        all_readings = temp_db.get_readings(limit=200)
        assert len(all_readings) == 100


# ---------------------------------------------------------------------------
# Echoes
# ---------------------------------------------------------------------------

class TestEchoes:
    def test_add_echo(self, temp_db):
        """Add a single echo and retrieve it."""
        temp_db.add_echo(
            pattern_type='morning_stress',
            message='Your mornings tend to be stressful.',
            detail='Avg morning stress 72 vs afternoon 45',
        )
        echoes = temp_db.get_echoes(limit=10)
        assert len(echoes) == 1
        assert echoes[0]['pattern_type'] == 'morning_stress'
        assert echoes[0]['message'] == 'Your mornings tend to be stressful.'
        assert echoes[0]['detail'] == 'Avg morning stress 72 vs afternoon 45'
        assert echoes[0]['seen'] == 0

    def test_batch_add_echoes(self, temp_db):
        """batch_add_echoes inserts multiple echoes in one transaction."""
        batch = [
            {'pattern_type': 'meeting_spike', 'message': 'Stress spikes during meetings.'},
            {'pattern_type': 'recovery', 'message': 'You recover quickly after peaks.', 'detail': '5 min avg'},
        ]
        temp_db.batch_add_echoes(batch)
        echoes = temp_db.get_echoes(limit=10)
        assert len(echoes) == 2

    def test_mark_echoes_seen(self, temp_db):
        """mark_echoes_seen sets seen=1 for all unseen echoes."""
        temp_db.add_echo('test', 'Echo 1')
        temp_db.add_echo('test', 'Echo 2')

        assert temp_db.get_unseen_echo_count() == 2

        temp_db.mark_echoes_seen()
        assert temp_db.get_unseen_echo_count() == 0

        # Echoes still exist
        echoes = temp_db.get_echoes(limit=10)
        assert len(echoes) == 2
        assert all(e['seen'] == 1 for e in echoes)

    def test_get_echoes_order(self, temp_db):
        """Echoes returned in descending discovered_at order."""
        for i in range(3):
            temp_db.add_echo('test', f'Echo {i}')
            time.sleep(0.01)  # Ensure different timestamps

        echoes = temp_db.get_echoes(limit=10)
        times = [e['discovered_at'] for e in echoes]
        assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags:
    def test_add_and_get_tag(self, temp_db):
        """Add a tag and retrieve it."""
        ts = datetime.now().isoformat()
        tag_id = temp_db.add_tag(ts, 'coffee', 'Had a double espresso')
        assert tag_id >= 1

        tags = temp_db.get_tags()
        assert len(tags) == 1
        assert tags[0]['label'] == 'coffee'
        assert tags[0]['notes'] == 'Had a double espresso'
        assert tags[0]['timestamp'] == ts

    def test_get_tags_by_time_range(self, temp_db):
        """Filter tags by time range."""
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        today = datetime.now().isoformat()

        temp_db.add_tag(yesterday, 'walk', 'Morning walk')
        temp_db.add_tag(today, 'meeting', 'Standup')

        today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        today_end = datetime.now().replace(hour=23, minute=59, second=59).isoformat()

        tags = temp_db.get_tags(start_time=today_start, end_time=today_end)
        assert len(tags) == 1
        assert tags[0]['label'] == 'meeting'


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

class TestBaselines:
    def test_update_and_get_baseline(self, temp_db):
        """Store and retrieve a personal baseline."""
        temp_db.update_baseline('f0_mean', mean=175.0, std=20.0, samples=50)
        bl = temp_db.get_baseline('f0_mean')
        assert bl is not None
        assert bl['metric'] == 'f0_mean'
        assert bl['mean'] == pytest.approx(175.0)
        assert bl['std'] == pytest.approx(20.0)
        assert bl['samples'] == 50

    def test_get_baseline_missing(self, temp_db):
        """get_baseline returns None for unknown metric."""
        assert temp_db.get_baseline('nonexistent') is None

    def test_get_all_baselines(self, temp_db):
        """get_all_baselines returns a dict keyed by metric name."""
        temp_db.update_baseline('f0_mean', 175.0, 20.0, 50)
        temp_db.update_baseline('rms_energy', 0.04, 0.01, 50)

        baselines = temp_db.get_all_baselines()
        assert 'f0_mean' in baselines
        assert 'rms_energy' in baselines
        assert baselines['f0_mean']['mean'] == pytest.approx(175.0)

    def test_update_baseline_overwrites(self, temp_db):
        """Updating a baseline for the same metric replaces the old one."""
        temp_db.update_baseline('f0_mean', 175.0, 20.0, 50)
        temp_db.update_baseline('f0_mean', 200.0, 30.0, 100)

        bl = temp_db.get_baseline('f0_mean')
        assert bl['mean'] == pytest.approx(200.0)
        assert bl['samples'] == 100


# ---------------------------------------------------------------------------
# Speaker Profiles
# ---------------------------------------------------------------------------

class TestSpeakerProfiles:
    def test_save_and_get_speaker_profile(self, temp_db):
        """Save a speaker profile and retrieve it."""
        import numpy as np
        embedding = np.random.randn(192).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        temp_db.save_speaker_profile(
            embedding=embedding.tobytes(),
            embedding_dim=192,
            num_samples=5,
            threshold=0.28,
        )

        profile = temp_db.get_speaker_profile()
        assert profile is not None
        assert profile['embedding_dim'] == 192
        assert profile['num_enrollment_samples'] == 5
        assert profile['enrollment_completed'] == 1
        assert profile['similarity_threshold'] == pytest.approx(0.28)

        # Verify embedding round-trip
        recovered = np.frombuffer(profile['embedding'], dtype=np.float32)
        np.testing.assert_allclose(recovered, embedding, atol=1e-7)

    def test_delete_speaker_profile(self, temp_db):
        """Deleting a profile removes it from the database."""
        import numpy as np
        embedding = np.random.randn(192).astype(np.float32)
        temp_db.save_speaker_profile(embedding.tobytes(), 192, 5, 0.28)

        assert temp_db.get_speaker_profile() is not None
        temp_db.delete_speaker_profile()
        assert temp_db.get_speaker_profile() is None

    def test_enrollment_samples(self, temp_db):
        """Add enrollment samples and retrieve them."""
        import numpy as np
        for mood in ['neutral', 'animated', 'calm']:
            emb = np.random.randn(192).astype(np.float32)
            temp_db.add_enrollment_sample(mood, emb.tobytes(), 10.0)

        samples = temp_db.get_enrollment_samples()
        assert len(samples) == 3
        assert samples[0]['mood_label'] == 'neutral'
        assert samples[1]['mood_label'] == 'animated'
        assert samples[2]['mood_label'] == 'calm'
        assert all(s['duration_sec'] == pytest.approx(10.0) for s in samples)

    def test_clear_enrollment_samples(self, temp_db):
        """clear_enrollment_samples removes all samples."""
        import numpy as np
        emb = np.random.randn(192).astype(np.float32)
        temp_db.add_enrollment_sample('neutral', emb.tobytes(), 10.0)
        assert len(temp_db.get_enrollment_samples()) == 1

        temp_db.clear_enrollment_samples()
        assert len(temp_db.get_enrollment_samples()) == 0


# ---------------------------------------------------------------------------
# User State
# ---------------------------------------------------------------------------

class TestUserState:
    def test_set_and_get(self, temp_db):
        temp_db.set_user_state('onboarding_completed', '1')
        assert temp_db.get_user_state('onboarding_completed') == '1'

    def test_default_value(self, temp_db):
        assert temp_db.get_user_state('nonexistent', 'default') == 'default'

    def test_overwrite(self, temp_db):
        temp_db.set_user_state('rainfall', '3')
        temp_db.set_user_state('rainfall', '5')
        assert temp_db.get_user_state('rainfall') == '5'


# ---------------------------------------------------------------------------
# Briefings
# ---------------------------------------------------------------------------

class TestBriefings:
    def test_insert_and_get_briefing(self, temp_db):
        today_str = date.today().isoformat()
        temp_db.insert_briefing(today_str, 'morning', '{"headline": "Good morning!"}')

        content = temp_db.get_briefing(today_str, 'morning')
        assert content is not None
        assert 'Good morning!' in content

    def test_get_briefing_missing(self, temp_db):
        assert temp_db.get_briefing('2020-01-01', 'morning') is None

    def test_delete_briefing(self, temp_db):
        today_str = date.today().isoformat()
        temp_db.insert_briefing(today_str, 'morning', 'test')
        assert temp_db.get_briefing(today_str, 'morning') is not None

        temp_db.delete_briefing(today_str, 'morning')
        assert temp_db.get_briefing(today_str, 'morning') is None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_log_and_retrieve(self, temp_db):
        temp_db.log_notification('threshold', 'High Stress', 'Stress hit 85')
        log = temp_db.get_notification_log(limit=10)
        assert len(log) == 1
        assert log[0]['type'] == 'threshold'
        assert log[0]['title'] == 'High Stress'

    def test_count_notifications_since(self, temp_db):
        temp_db.log_notification('milestone', 'First Reading', '')
        since = (datetime.now() - timedelta(hours=1)).isoformat()
        assert temp_db.count_notifications_since(since) == 1

    def test_notification_prefs(self, temp_db):
        temp_db.set_notification_pref('quiet_start', '22')
        assert temp_db.get_notification_pref('quiet_start') == '22'
        assert temp_db.get_notification_pref('nonexistent', 'default') == 'default'

        all_prefs = temp_db.get_all_notification_prefs()
        assert 'quiet_start' in all_prefs
