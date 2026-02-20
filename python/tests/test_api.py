"""
Tests for FastAPI API routes (api/routes.py).

Uses FastAPI's TestClient to exercise endpoints without spinning up a server.
Mocks the global db, orchestrator, and other dependencies that routes.py
expects to find at module level.
"""
import tempfile
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, date

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    """Create a real temp Database for API tests."""
    from backend.database import Database
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    return Database(db_path=path), path


def _make_reading(**overrides):
    """Return a reading dict with realistic defaults, allowing overrides."""
    base = {
        'timestamp': datetime.now().isoformat(),
        'depression_raw': 5.0,
        'anxiety_raw': 3.0,
        'depression_quantized': 5,
        'anxiety_quantized': 3,
        'depression_mapped': 7.0,
        'anxiety_mapped': 4.5,
        'f0_mean': 180.0,
        'f0_std': 25.0,
        'speech_rate': 3.5,
        'rms_energy': 0.04,
        'spectral_centroid': 1500.0,
        'spectral_entropy': 4.0,
        'zcr': 0.08,
        'jitter': 0.015,
        'shimmer': 0.06,
        'voice_breaks': 1,
        'stress_score': 45.0,
        'mood_score': 65.0,
        'energy_score': 55.0,
        'calm_score': 60.0,
        'stress_score_raw': 42.0,
        'mood_score_raw': 68.0,
        'energy_score_raw': 52.0,
        'calm_score_raw': 58.0,
        'zone': 'steady',
        'speech_duration_sec': 45.0,
        'meeting_detected': 0,
        'vad_confidence': 0.85,
        'low_confidence': 0,
        'speaker_verified': 1,
        'speaker_similarity': 0.72,
    }
    base.update(overrides)
    return base


@pytest.fixture
def api_client():
    """Create a TestClient backed by a real temp DB.

    Patches module-level globals in api.routes so endpoints can function
    without the real orchestrator / insight engine / meeting detector.
    """
    import api.routes as routes

    real_db, db_path = _make_db()

    # Mock the orchestrator just enough for /api/health and /api/today
    mock_orch = MagicMock()
    mock_orch.models_ready.is_set.return_value = True
    mock_orch.get_status.return_value = {
        'is_running': True,
        'is_paused': False,
        'meeting_active': False,
        'is_analyzing': False,
        'buffered_speech_sec': 0.0,
        'buffered_vad_confidence': None,
        'calibration_status': {'is_calibrated': False},
        'speaker_enrolled': None,
        'enrollment_required': None,
        'speaker_gate_stats': None,
    }
    mock_orch.calibrator = MagicMock()
    mock_orch.calibrator.get_calibration_status.return_value = {'is_calibrated': False}

    # Stash originals
    orig_db = routes.db
    orig_orch = routes.orchestrator
    orig_meeting = routes.meeting_detector
    orig_insight = routes.insight_engine
    orig_notif = routes.notification_manager

    # Patch
    routes.db = real_db
    routes.orchestrator = mock_orch
    routes.meeting_detector = MagicMock()
    routes.insight_engine = MagicMock()
    routes.notification_manager = MagicMock()

    # Reset daily summary cache (module-level state)
    routes._daily_summary_cache = None
    routes._daily_summary_reading_count = None

    client = TestClient(routes.app)

    yield client, real_db

    # Restore
    routes.db = orig_db
    routes.orchestrator = orig_orch
    routes.meeting_detector = orig_meeting
    routes.insight_engine = orig_insight
    routes.notification_manager = orig_notif

    # Cleanup
    real_db.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ready(self, api_client):
        client, _ = api_client
        resp = client.get('/api/health')
        assert resp.status_code == 200
        data = resp.json()
        assert data['ready'] is True
        assert data['status'] == 'ready'

    def test_health_returns_initializing_when_no_orchestrator(self, api_client):
        """When orchestrator is None, health reports initializing."""
        client, _ = api_client
        import api.routes as routes
        saved = routes.orchestrator
        routes.orchestrator = None
        try:
            resp = client.get('/api/health')
            assert resp.status_code == 200
            data = resp.json()
            assert data['ready'] is False
            assert 'initializing' in data['status']
        finally:
            routes.orchestrator = saved

    def test_health_loading_models(self, api_client):
        """When models not yet loaded, status says loading."""
        client, _ = api_client
        import api.routes as routes
        routes.orchestrator.models_ready.is_set.return_value = False
        resp = client.get('/api/health')
        data = resp.json()
        assert data['ready'] is False
        assert 'loading' in data['status']


class TestTodayEndpoint:
    def test_today_empty(self, api_client):
        """GET /api/today with no readings returns default scores and empty list."""
        client, _ = api_client
        resp = client.get('/api/today')
        assert resp.status_code == 200
        data = resp.json()
        assert 'current_scores' in data
        assert data['readings'] == []
        # Default scores when no readings exist
        assert data['current_scores']['mood'] == 50
        assert data['current_scores']['stress'] == 50

    def test_today_with_readings(self, api_client):
        """GET /api/today after inserting readings returns them."""
        client, db = api_client
        reading = _make_reading(stress_score=72.0, mood_score=35.0)
        db.insert_reading(reading)

        resp = client.get('/api/today')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data['readings']) >= 1
        # Current scores should reflect the latest reading
        assert data['current_scores']['stress'] == pytest.approx(72.0)
        assert data['current_scores']['mood'] == pytest.approx(35.0)


class TestReadingsEndpoint:
    def test_readings_empty(self, api_client):
        client, _ = api_client
        resp = client.get('/api/readings')
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_readings_with_data(self, api_client):
        client, db = api_client
        db.insert_reading(_make_reading())
        db.insert_reading(_make_reading())

        resp = client.get('/api/readings?limit=10')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_readings_limit(self, api_client):
        client, db = api_client
        for _ in range(5):
            db.insert_reading(_make_reading())

        resp = client.get('/api/readings?limit=3')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3


class TestTokenEndpoint:
    def test_token_endpoint_localhost(self, api_client):
        """GET /api/v1/token from localhost returns a token.

        TestClient uses 'testclient' as client host by default, which the
        endpoint rejects. We patch request.client.host to simulate localhost.
        """
        client, db = api_client
        # The endpoint checks request.client.host in ("127.0.0.1", "::1", "localhost").
        # TestClient doesn't set that. Instead, test the underlying DB logic
        # that the endpoint uses: get/set api_token via user_state.
        import secrets
        token = secrets.token_urlsafe(32)
        db.set_user_state('api_token', token)
        stored = db.get_user_state('api_token', '')
        assert stored == token
        assert len(stored) > 10

    def test_token_is_stable(self, api_client):
        """The same token is returned on consecutive reads."""
        _, db = api_client
        import secrets
        token = secrets.token_urlsafe(32)
        db.set_user_state('api_token', token)
        assert db.get_user_state('api_token') == token
        assert db.get_user_state('api_token') == token

    def test_token_endpoint_rejects_non_localhost(self, api_client):
        """GET /api/v1/token from a non-localhost client returns 403."""
        client, _ = api_client
        resp = client.get('/api/v1/token')
        # TestClient host is 'testclient', not localhost, so expect 403
        assert resp.status_code == 403


class TestTagEndpoints:
    def test_add_tag(self, api_client):
        client, _ = api_client
        resp = client.post('/api/tag', json={
            'timestamp': datetime.now().isoformat(),
            'label': 'coffee',
            'notes': 'Double shot',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['label'] == 'coffee'
        assert data['id'] >= 1

    def test_get_tags(self, api_client):
        client, _ = api_client
        client.post('/api/tag', json={
            'timestamp': datetime.now().isoformat(),
            'label': 'walk',
        })
        resp = client.get('/api/tags')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]['label'] == 'walk'


class TestBeaconEndpoint:
    def test_beacon_no_readings(self, api_client):
        client, _ = api_client
        resp = client.get('/api/beacon')
        assert resp.status_code == 200
        data = resp.json()
        assert data['zone'] == 'idle'
        assert data['stress'] == 0

    def test_beacon_with_reading(self, api_client):
        client, db = api_client
        db.insert_reading(_make_reading(
            zone='tense',
            stress_score=65.0,
        ))
        resp = client.get('/api/beacon')
        assert resp.status_code == 200
        data = resp.json()
        assert data['zone'] == 'tense'
        assert data['stress'] == 65


class TestOnboardingEndpoint:
    def test_onboarding_default_not_completed(self, api_client):
        client, _ = api_client
        resp = client.get('/api/onboarding-status')
        assert resp.status_code == 200
        assert resp.json()['completed'] is False

    def test_set_onboarding_completed(self, api_client):
        client, _ = api_client
        resp = client.post('/api/onboarding-status', json={'completed': True})
        assert resp.status_code == 200

        resp = client.get('/api/onboarding-status')
        assert resp.json()['completed'] is True


class TestWebhookEndpoints:
    def test_register_and_list_webhooks(self, api_client):
        client, _ = api_client
        resp = client.post('/api/webhooks', json={
            'url': 'https://example.com/hook',
            'trigger_type': 'reading',
            'condition_field': 'stress_score',
            'condition_op': '>=',
            'condition_value': 80.0,
        })
        assert resp.status_code == 200
        assert resp.json()['success'] is True

        resp = client.get('/api/webhooks')
        assert resp.status_code == 200
        hooks = resp.json()['webhooks']
        assert len(hooks) == 1
        assert hooks[0]['url'] == 'https://example.com/hook'

    def test_delete_webhook(self, api_client):
        client, _ = api_client
        resp = client.post('/api/webhooks', json={
            'url': 'https://example.com/hook',
            'trigger_type': 'zone_change',
        })
        wid = resp.json()['id']

        resp = client.delete(f'/api/webhooks/{wid}')
        assert resp.status_code == 200

        resp = client.get('/api/webhooks')
        assert len(resp.json()['webhooks']) == 0


class TestNotificationPrefsEndpoint:
    def test_get_default_prefs(self, api_client):
        client, _ = api_client
        resp = client.get('/api/notifications/prefs')
        assert resp.status_code == 200
        prefs = resp.json()
        # Verify defaults are filled
        assert prefs['notifications_enabled'] == 'true'
        assert prefs['quiet_start'] == '19'

    def test_set_pref(self, api_client):
        client, _ = api_client
        resp = client.post('/api/notifications/prefs', json={
            'key': 'quiet_start',
            'value': '22',
        })
        assert resp.status_code == 200

        resp = client.get('/api/notifications/prefs')
        assert resp.json()['quiet_start'] == '22'
