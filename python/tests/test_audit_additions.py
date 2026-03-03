"""
Tests for Phase 3B audit additions:
  1. Schema migration framework (database.py)
  2. ReadingInsert Pydantic validation (schemas.py)
  3. Custom exception classes (exceptions.py)
  4. API exception handlers via TestClient
  5. New endpoints: /api/health/ready, /api/config
  6. has_data fields on beacon
  7. Onboarding validation (speaker enrollment gate)

Imports helpers from test_api.py and follows the same fixture pattern.
"""
import tempfile
import os
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from fastapi.testclient import TestClient
from pydantic import ValidationError

# Re-use helpers from existing test suite
from tests.test_api import _make_db, _make_reading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    """TestClient backed by a real temp DB — mirrors test_api.api_client."""
    import api.routes as routes
    import api.dependencies as deps
    from api.routers import readings as readings_router

    real_db, db_path = _make_db()

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
    # Speaker verifier mock — default: not enrolled
    mock_orch.speaker_verifier = MagicMock()
    mock_orch.speaker_verifier.get_status.return_value = {'enrolled': False}

    orig_db = deps.db
    orig_orch = deps.orchestrator
    orig_meeting = deps.meeting_detector
    orig_insight = deps.insight_engine
    orig_notif = deps.notification_manager

    deps.db = real_db
    deps.orchestrator = mock_orch
    deps.meeting_detector = MagicMock()
    deps.insight_engine = MagicMock()
    deps.notification_manager = MagicMock()

    readings_router._daily_summary_cache = None
    readings_router._daily_summary_reading_count = None

    client = TestClient(routes.app)

    yield client, real_db, mock_orch

    deps.db = orig_db
    deps.orchestrator = orig_orch
    deps.meeting_detector = orig_meeting
    deps.insight_engine = orig_insight
    deps.notification_manager = orig_notif

    real_db.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 1. Schema Migration Framework (database.py)
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_schema_version_table_exists(self):
        """schema_version table is created during DB init."""
        db, path = _make_db()
        try:
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            assert cursor.fetchone() is not None, "schema_version table missing"
        finally:
            db.close()
            os.unlink(path)

    def test_migration_001_indexes_applied(self):
        """Migration 001 creates the expected indexes."""
        db, path = _make_db()
        try:
            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            index_names = {row['name'] for row in cursor.fetchall()}

            expected = {
                'idx_readings_timestamp',
                'idx_daily_summaries_date',
                'idx_notification_log_sent_at',
                'idx_grove_date',
                'idx_echoes_discovered_at',
                'idx_echoes_seen',
            }
            for idx in expected:
                assert idx in index_names, f"Index {idx} not found in {index_names}"
        finally:
            db.close()
            os.unlink(path)

    def test_migration_version_recorded(self):
        """After init, schema_version contains migration 1."""
        db, path = _make_db()
        try:
            cursor = db.conn.cursor()
            cursor.execute("SELECT version, description FROM schema_version ORDER BY version")
            rows = cursor.fetchall()
            assert len(rows) >= 1
            assert rows[0]['version'] == 1
            assert 'index' in rows[0]['description'].lower()
        finally:
            db.close()
            os.unlink(path)

    def test_health_check_returns_true(self):
        """health_check() returns True on a healthy database."""
        db, path = _make_db()
        try:
            assert db.health_check() is True
        finally:
            db.close()
            os.unlink(path)

    def test_health_check_returns_false_after_close(self):
        """health_check() returns False after the connection is closed."""
        db, path = _make_db()
        db.close()
        try:
            assert db.health_check() is False
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_wal_mode_enabled(self):
        """Database uses WAL journal mode for concurrent reads."""
        db, path = _make_db()
        try:
            cursor = db.conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == 'wal'
        finally:
            db.close()
            os.unlink(path)


# ---------------------------------------------------------------------------
# 2. ReadingInsert Pydantic Validation (schemas.py)
# ---------------------------------------------------------------------------

class TestReadingInsertValidation:
    def test_valid_reading_passes(self):
        """A reading with all valid fields passes validation."""
        from api.schemas import ReadingInsert
        r = ReadingInsert(**_make_reading())
        assert r.stress_score == 45.0
        assert r.zone == 'steady'

    def test_score_clamped_high(self):
        """Scores above 100 are clamped to 100."""
        from api.schemas import ReadingInsert
        r = ReadingInsert(mood_score=150.0)
        assert r.mood_score == 100.0

    def test_score_clamped_low(self):
        """Negative scores are clamped to 0."""
        from api.schemas import ReadingInsert
        r = ReadingInsert(stress_score=-20.0)
        assert r.stress_score == 0.0

    def test_multiple_scores_clamped(self):
        """All score fields are clamped independently."""
        from api.schemas import ReadingInsert
        r = ReadingInsert(
            mood_score=200.0,
            energy_score=-50.0,
            calm_score=100.0,
            wellbeing_score=999.0,
        )
        assert r.mood_score == 100.0
        assert r.energy_score == 0.0
        assert r.calm_score == 100.0
        assert r.wellbeing_score == 100.0

    def test_invalid_zone_rejected(self):
        """An invalid zone value raises ValidationError."""
        from api.schemas import ReadingInsert
        with pytest.raises(ValidationError) as exc_info:
            ReadingInsert(zone='invalid_zone')
        assert 'zone' in str(exc_info.value).lower()

    def test_valid_zones_accepted(self):
        """All four valid zones pass validation."""
        from api.schemas import ReadingInsert
        for zone in ('stressed', 'tense', 'steady', 'calm'):
            r = ReadingInsert(zone=zone)
            assert r.zone == zone

    def test_f0_mean_above_1000_rejected(self):
        """f0_mean > 1000 raises ValidationError."""
        from api.schemas import ReadingInsert
        with pytest.raises(ValidationError) as exc_info:
            ReadingInsert(f0_mean=1500.0)
        assert 'f0_mean' in str(exc_info.value).lower()

    def test_f0_mean_negative_rejected(self):
        """f0_mean < 0 raises ValidationError."""
        from api.schemas import ReadingInsert
        with pytest.raises(ValidationError):
            ReadingInsert(f0_mean=-10.0)

    def test_f0_mean_at_boundary_passes(self):
        """f0_mean of exactly 0 and 1000 are valid."""
        from api.schemas import ReadingInsert
        r0 = ReadingInsert(f0_mean=0.0)
        assert r0.f0_mean == 0.0
        r1000 = ReadingInsert(f0_mean=1000.0)
        assert r1000.f0_mean == 1000.0

    def test_negative_speech_duration_rejected(self):
        """Negative speech_duration_sec raises ValidationError."""
        from api.schemas import ReadingInsert
        with pytest.raises(ValidationError):
            ReadingInsert(speech_duration_sec=-5.0)

    def test_none_values_pass(self):
        """All-None ReadingInsert (minimal) is valid."""
        from api.schemas import ReadingInsert
        r = ReadingInsert()
        assert r.stress_score is None
        assert r.zone is None
        assert r.f0_mean is None


# ---------------------------------------------------------------------------
# 3. Custom Exception Classes (exceptions.py)
# ---------------------------------------------------------------------------

class TestExceptionClasses:
    def test_database_not_ready(self):
        """DatabaseNotReady has status_code=503, retry_after=5."""
        from api.exceptions import DatabaseNotReady
        exc = DatabaseNotReady()
        assert exc.status_code == 503
        assert exc.retry_after == 5
        assert exc.code == 'DB_NOT_READY'
        assert 'database' in exc.message.lower()

    def test_model_not_loaded(self):
        """ModelNotLoaded has status_code=503, retry_after=10."""
        from api.exceptions import ModelNotLoaded
        exc = ModelNotLoaded()
        assert exc.status_code == 503
        assert exc.retry_after == 10
        assert exc.code == 'MODELS_LOADING'
        assert 'model' in exc.message.lower()

    def test_service_not_ready_default(self):
        """ServiceNotReady with default message includes 'Service'."""
        from api.exceptions import ServiceNotReady
        exc = ServiceNotReady()
        assert exc.status_code == 503
        assert exc.retry_after == 5
        assert exc.code == 'SERVICE_NOT_READY'
        assert 'service' in exc.message.lower()

    def test_service_not_ready_custom(self):
        """ServiceNotReady with custom service name."""
        from api.exceptions import ServiceNotReady
        exc = ServiceNotReady("Insight engine")
        assert 'insight engine' in exc.message.lower()

    def test_lucid_error_base(self):
        """LucidError base class stores all fields."""
        from api.exceptions import LucidError
        exc = LucidError("Test error", "TEST_CODE", 418, 30)
        assert exc.message == "Test error"
        assert exc.code == "TEST_CODE"
        assert exc.status_code == 418
        assert exc.retry_after == 30

    def test_lucid_error_defaults(self):
        """LucidError defaults: status_code=500, retry_after=None."""
        from api.exceptions import LucidError
        exc = LucidError("err", "ERR")
        assert exc.status_code == 500
        assert exc.retry_after is None

    def test_exception_hierarchy(self):
        """All custom exceptions are subclasses of LucidError and Exception."""
        from api.exceptions import LucidError, DatabaseNotReady, ModelNotLoaded, ServiceNotReady
        assert issubclass(DatabaseNotReady, LucidError)
        assert issubclass(ModelNotLoaded, LucidError)
        assert issubclass(ServiceNotReady, LucidError)
        assert issubclass(LucidError, Exception)


# ---------------------------------------------------------------------------
# 4. API Exception Handlers (structured 503 via TestClient)
# ---------------------------------------------------------------------------

class TestAPIExceptionHandlers:
    def test_readings_503_when_db_none(self, api_client):
        """GET /api/readings returns structured 503 when db is None."""
        client, db, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/readings')
            assert resp.status_code == 503
            data = resp.json()
            assert 'error' in data
            assert 'code' in data
            assert data['code'] == 'DB_NOT_READY'
            assert 'retry_after' in data
            assert data['retry_after'] == 5
        finally:
            deps.db = saved

    def test_readings_503_has_retry_after_header(self, api_client):
        """503 response includes Retry-After header."""
        client, db, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/readings')
            assert resp.status_code == 503
            assert 'retry-after' in resp.headers
            assert resp.headers['retry-after'] == '5'
        finally:
            deps.db = saved

    def test_today_503_when_db_none(self, api_client):
        """GET /api/today returns 503 with structured error when db is None."""
        client, _, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/today')
            assert resp.status_code == 503
            data = resp.json()
            assert data['code'] == 'DB_NOT_READY'
            assert data['retry_after'] == 5
        finally:
            deps.db = saved

    def test_tags_503_when_db_none(self, api_client):
        """GET /api/tags returns 503 with structured error when db is None."""
        client, _, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/tags')
            assert resp.status_code == 503
            data = resp.json()
            assert data['code'] == 'DB_NOT_READY'
        finally:
            deps.db = saved


# ---------------------------------------------------------------------------
# 5. New Endpoints: /api/health/ready, /api/config
# ---------------------------------------------------------------------------

class TestHealthReadyEndpoint:
    def test_health_ready_all_services_up(self, api_client):
        """GET /api/health/ready returns 200 when all services are ready."""
        client, db, _ = api_client
        resp = client.get('/api/health/ready')
        assert resp.status_code == 200
        data = resp.json()
        assert data['ready'] is True
        assert 'checks' in data
        assert data['checks']['database'] is True
        assert data['checks']['orchestrator'] is True
        assert data['checks']['models_loaded'] is True

    def test_health_ready_503_when_db_none(self, api_client):
        """GET /api/health/ready returns 503 when db is None."""
        client, _, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/health/ready')
            assert resp.status_code == 503
            data = resp.json()
            assert data['ready'] is False
            assert data['checks']['database'] is False
        finally:
            deps.db = saved

    def test_health_ready_503_when_models_not_loaded(self, api_client):
        """GET /api/health/ready returns 503 when models not loaded."""
        client, _, mock_orch = api_client
        mock_orch.models_ready.is_set.return_value = False
        resp = client.get('/api/health/ready')
        assert resp.status_code == 503
        data = resp.json()
        assert data['ready'] is False
        assert data['checks']['models_loaded'] is False

    def test_health_ready_includes_speaker_enrolled(self, api_client):
        """Response includes speaker_enrolled status."""
        client, _, mock_orch = api_client
        mock_orch.speaker_verifier.get_status.return_value = {'enrolled': True}
        resp = client.get('/api/health/ready')
        data = resp.json()
        assert 'speaker_enrolled' in data['checks']
        assert data['checks']['speaker_enrolled'] is True

    def test_health_ready_has_retry_after_header_on_503(self, api_client):
        """503 from /api/health/ready includes Retry-After header."""
        client, _, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/health/ready')
            assert resp.status_code == 503
            assert 'retry-after' in resp.headers
            assert resp.headers['retry-after'] == '5'
        finally:
            deps.db = saved


class TestConfigEndpoint:
    def test_config_returns_zone_thresholds(self, api_client):
        """GET /api/config returns zone_thresholds with stressed/tense keys."""
        client, _, _ = api_client
        resp = client.get('/api/config')
        assert resp.status_code == 200
        data = resp.json()
        assert 'zone_thresholds' in data
        assert 'stressed' in data['zone_thresholds']
        assert 'tense' in data['zone_thresholds']
        # Thresholds should be numeric
        assert isinstance(data['zone_thresholds']['stressed'], (int, float))

    def test_config_returns_zone_colors(self, api_client):
        """GET /api/config returns zone_colors for all four zones."""
        client, _, _ = api_client
        resp = client.get('/api/config')
        data = resp.json()
        assert 'zone_colors' in data
        for zone in ('calm', 'steady', 'tense', 'stressed'):
            assert zone in data['zone_colors'], f"Missing color for {zone}"
            assert data['zone_colors'][zone].startswith('#'), f"Color for {zone} not a hex color"

    def test_config_returns_brand_colors(self, api_client):
        """GET /api/config returns brand_colors with primary/secondary."""
        client, _, _ = api_client
        resp = client.get('/api/config')
        data = resp.json()
        assert 'brand_colors' in data
        assert 'primary' in data['brand_colors']
        assert 'secondary' in data['brand_colors']

    def test_config_returns_api_port(self, api_client):
        """GET /api/config returns api_port as an integer."""
        client, _, _ = api_client
        resp = client.get('/api/config')
        data = resp.json()
        assert 'api_port' in data
        assert isinstance(data['api_port'], int)


# ---------------------------------------------------------------------------
# 6. has_data Fields
# ---------------------------------------------------------------------------

class TestHasDataFields:
    def test_beacon_has_data_false_when_no_readings(self, api_client):
        """GET /api/beacon returns has_data: false when DB is empty."""
        client, _, _ = api_client
        resp = client.get('/api/beacon')
        assert resp.status_code == 200
        data = resp.json()
        assert data['has_data'] is False

    def test_beacon_has_data_true_after_reading(self, api_client):
        """GET /api/beacon returns has_data: true after inserting a reading."""
        client, db, _ = api_client
        db.insert_reading(_make_reading(zone='steady', stress_score=40.0))

        resp = client.get('/api/beacon')
        assert resp.status_code == 200
        data = resp.json()
        assert data['has_data'] is True
        assert data['zone'] == 'steady'

    def test_beacon_has_data_false_when_db_none(self, api_client):
        """GET /api/beacon returns has_data: false when db is None (graceful)."""
        client, _, _ = api_client
        import api.dependencies as deps

        saved = deps.db
        deps.db = None
        try:
            resp = client.get('/api/beacon')
            assert resp.status_code == 200
            data = resp.json()
            assert data['has_data'] is False
            assert data['zone'] == 'idle'
        finally:
            deps.db = saved


# ---------------------------------------------------------------------------
# 7. Onboarding Validation (speaker enrollment gate)
# ---------------------------------------------------------------------------

class TestOnboardingValidation:
    def test_set_onboarding_completed_fails_without_enrollment(self, api_client):
        """POST /api/onboarding-status completed=true fails when speaker not enrolled."""
        client, _, mock_orch = api_client
        # Speaker not enrolled (default mock)
        mock_orch.speaker_verifier.get_status.return_value = {'enrolled': False}

        resp = client.post('/api/onboarding-status', json={'completed': True})
        assert resp.status_code == 400
        assert 'enrollment' in resp.json()['detail'].lower()

    def test_set_onboarding_completed_succeeds_with_enrollment(self, api_client):
        """POST /api/onboarding-status completed=true succeeds when speaker enrolled."""
        client, _, mock_orch = api_client
        mock_orch.speaker_verifier.get_status.return_value = {'enrolled': True}

        resp = client.post('/api/onboarding-status', json={'completed': True})
        assert resp.status_code == 200
        assert resp.json()['success'] is True

        # Verify it persisted
        resp = client.get('/api/onboarding-status')
        assert resp.json()['completed'] is True

    def test_set_onboarding_uncompleted_always_succeeds(self, api_client):
        """POST /api/onboarding-status completed=false always succeeds."""
        client, _, mock_orch = api_client
        # Speaker not enrolled — should not matter for uncompleting
        mock_orch.speaker_verifier.get_status.return_value = {'enrolled': False}

        resp = client.post('/api/onboarding-status', json={'completed': False})
        assert resp.status_code == 200
        assert resp.json()['success'] is True

    def test_onboarding_validation_with_no_verifier(self, api_client):
        """Onboarding complete succeeds when speaker_verifier is None (no gate)."""
        client, _, mock_orch = api_client
        mock_orch.speaker_verifier = None

        resp = client.post('/api/onboarding-status', json={'completed': True})
        assert resp.status_code == 200
        assert resp.json()['success'] is True
