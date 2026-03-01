"""
Tests for backend.speaker_gate.SpeakerGate

Uses mock SpeakerVerifier to control verification outcomes without
loading the real ECAPA-TDNN model. Tests initialization, verification
flow, momentum, sandwich recovery, and stats tracking.
"""
import time
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_verifier(verify_return=(True, 0.65)):
    """Create a mock SpeakerVerifier with configurable verify_segment return."""
    mock = MagicMock()
    mock.verify_segment.return_value = verify_return
    return mock


def _make_gate(mock_verifier, on_verified=None, segment_sec=0.1):
    """Create a SpeakerGate with short segment duration for fast tests."""
    import app_config as config

    # Temporarily override segment duration for faster tests
    original_segment = config.SPEAKER_GATE_SEGMENT_SEC
    config.SPEAKER_GATE_SEGMENT_SEC = segment_sec

    from backend.speaker_gate import SpeakerGate
    gate = SpeakerGate(
        speaker_verifier=mock_verifier,
        sample_rate=16000,
        on_verified_callback=on_verified,
    )

    # Restore config after gate is created (segment_samples already computed)
    config.SPEAKER_GATE_SEGMENT_SEC = original_segment
    return gate


def _make_chunk(duration_sec=0.05, sr=16000):
    """Generate a short audio chunk (random noise)."""
    n = int(sr * duration_sec)
    return np.random.randn(n).astype(np.float32) * 0.1


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestGateInitialization:
    def test_gate_starts_with_expected_defaults(self):
        """Gate should initialize with zeroed stats and no momentum."""
        mock_v = _make_mock_verifier()
        gate = _make_gate(mock_v)

        stats = gate.get_stats()
        assert stats['segments_verified'] == 0
        assert stats['segments_rejected'] == 0
        assert stats['segments_sandwich_recovered'] == 0
        assert stats['total_segments'] == 0
        assert stats['pass_rate'] == 0
        assert stats['last_similarity'] is None
        assert stats['momentum_active'] is False
        assert isinstance(stats['recent_events'], list)
        assert len(stats['recent_events']) == 0

        gate.stop()

    def test_gate_has_worker_thread(self):
        """The gate should start a background worker thread."""
        mock_v = _make_mock_verifier()
        gate = _make_gate(mock_v)

        assert gate._worker_thread.is_alive()

        gate.stop()
        time.sleep(0.2)
        assert not gate._worker_thread.is_alive()


# ---------------------------------------------------------------------------
# Verification flow
# ---------------------------------------------------------------------------

class TestVerificationFlow:
    def test_verified_chunks_reach_callback(self):
        """Chunks from verified segments should be passed to on_verified_callback."""
        received_chunks = []

        def on_verified(chunk, confidence):
            received_chunks.append(chunk)

        mock_v = _make_mock_verifier(verify_return=(True, 0.65))
        gate = _make_gate(mock_v, on_verified=on_verified, segment_sec=0.05)

        # Feed enough audio to trigger at least one segment
        for _ in range(30):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.005)

        # Wait for worker to process
        time.sleep(0.5)

        assert len(received_chunks) > 0
        assert mock_v.verify_segment.called

        gate.stop()

    def test_rejected_chunks_do_not_reach_callback(self):
        """Chunks from rejected segments should NOT reach the callback."""
        received = []

        def on_verified(chunk, confidence):
            received.append(chunk)

        # Hard reject: similarity below sandwich threshold too
        mock_v = _make_mock_verifier(verify_return=(False, 0.10))
        gate = _make_gate(mock_v, on_verified=on_verified, segment_sec=0.05)

        for _ in range(30):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.005)

        time.sleep(0.5)

        assert len(received) == 0
        gate.stop()

    def test_stats_update_on_verification(self):
        """Stats should reflect verified/rejected counts."""
        mock_v = _make_mock_verifier(verify_return=(True, 0.55))
        gate = _make_gate(mock_v, segment_sec=0.05)

        for _ in range(30):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.005)

        time.sleep(0.5)

        stats = gate.get_stats()
        assert stats['segments_verified'] > 0
        assert stats['last_similarity'] is not None
        assert stats['last_similarity'] == pytest.approx(0.55)

        gate.stop()


# ---------------------------------------------------------------------------
# Embedding comparison (cosine similarity)
# ---------------------------------------------------------------------------

class TestEmbeddingComparison:
    def test_identical_embeddings_high_similarity(self):
        """Two identical L2-normalized embeddings have cosine similarity 1.0."""
        emb = np.random.randn(192).astype(np.float32)
        emb = emb / np.linalg.norm(emb)
        similarity = float(np.dot(emb, emb))
        assert similarity == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_embeddings_zero_similarity(self):
        """Orthogonal embeddings have cosine similarity ~0."""
        # Create two orthogonal vectors
        emb1 = np.zeros(192, dtype=np.float32)
        emb1[0] = 1.0
        emb2 = np.zeros(192, dtype=np.float32)
        emb2[1] = 1.0
        similarity = float(np.dot(emb1, emb2))
        assert similarity == pytest.approx(0.0, abs=1e-5)

    def test_opposite_embeddings_negative_similarity(self):
        """Opposite vectors have cosine similarity -1."""
        emb = np.random.randn(192).astype(np.float32)
        emb = emb / np.linalg.norm(emb)
        similarity = float(np.dot(emb, -emb))
        assert similarity == pytest.approx(-1.0, abs=1e-5)

    def test_similar_embeddings_above_threshold(self):
        """Slightly perturbed embeddings should still be above typical threshold (0.28)."""
        emb1 = np.random.randn(192).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)

        # Small perturbation
        noise = np.random.randn(192).astype(np.float32) * 0.05
        emb2 = emb1 + noise
        emb2 = emb2 / np.linalg.norm(emb2)

        similarity = float(np.dot(emb1, emb2))
        # With small noise on 192-dim vector, similarity should be well above
        # the speaker gate threshold of 0.28
        assert similarity > 0.7


# ---------------------------------------------------------------------------
# Gate decision logic (is_user)
# ---------------------------------------------------------------------------

class TestGateDecision:
    def test_high_similarity_accepted(self):
        """Similarity well above threshold should result in verification."""
        mock_v = _make_mock_verifier(verify_return=(True, 0.80))
        gate = _make_gate(mock_v, segment_sec=0.05)

        for _ in range(30):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.005)

        time.sleep(0.5)
        stats = gate.get_stats()
        assert stats['segments_verified'] > 0
        assert stats['segments_rejected'] == 0
        gate.stop()

    def test_low_similarity_rejected(self):
        """Similarity well below threshold should result in rejection."""
        mock_v = _make_mock_verifier(verify_return=(False, 0.10))
        gate = _make_gate(mock_v, segment_sec=0.05)

        for _ in range(30):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.005)

        time.sleep(0.5)
        stats = gate.get_stats()
        assert stats['segments_rejected'] > 0
        assert stats['segments_verified'] == 0
        gate.stop()


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

class TestMomentum:
    def test_momentum_activates_after_consecutive_verified(self):
        """Momentum activates after SPEAKER_GATE_MOMENTUM_WINDOW consecutive accepts."""
        import app_config as config
        mock_v = _make_mock_verifier(verify_return=(True, 0.65))
        gate = _make_gate(mock_v, segment_sec=0.03)

        # Feed enough segments to exceed momentum window (default 3)
        needed = config.SPEAKER_GATE_MOMENTUM_WINDOW + 2
        for seg in range(needed):
            for _ in range(20):
                gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
                time.sleep(0.002)
            time.sleep(0.2)

        time.sleep(0.5)
        stats = gate.get_stats()
        # After enough verified segments, momentum should be active
        if stats['segments_verified'] >= config.SPEAKER_GATE_MOMENTUM_WINDOW:
            assert stats['momentum_active'] is True

        gate.stop()


# ---------------------------------------------------------------------------
# Sandwich recovery
# ---------------------------------------------------------------------------

class TestSandwichRecovery:
    def test_sandwich_recovery_between_verified_segments(self):
        """A borderline reject sandwiched between two verified segments is recovered."""
        import app_config as config
        call_count = [0]
        recovered_chunks = []

        def on_verified(chunk, confidence):
            recovered_chunks.append(chunk)

        # Returns: verified, borderline-reject, verified
        sandwich_threshold = config.SPEAKER_GATE_SANDWICH_THRESHOLD
        returns = [
            (True, 0.65),                           # First: verified
            (False, sandwich_threshold + 0.01),     # Second: borderline reject (above sandwich thresh)
            (True, 0.65),                           # Third: verified (triggers sandwich recovery)
        ]

        def side_effect(audio, threshold=None):
            idx = min(call_count[0], len(returns) - 1)
            call_count[0] += 1
            return returns[idx]

        mock_v = MagicMock()
        mock_v.verify_segment.side_effect = side_effect

        gate = _make_gate(mock_v, on_verified=on_verified, segment_sec=0.03)

        # Feed 3 segments worth of audio
        for seg in range(3):
            for _ in range(15):
                gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
                time.sleep(0.002)
            time.sleep(0.3)

        time.sleep(0.5)
        stats = gate.get_stats()

        # If all 3 segments were processed, we should have sandwich recovery
        if stats['total_segments'] >= 3:
            assert stats['segments_sandwich_recovered'] >= 1

        gate.stop()


# ---------------------------------------------------------------------------
# Flush / Stop
# ---------------------------------------------------------------------------

class TestFlushAndStop:
    def test_flush_remaining_clears_buffer(self):
        """flush_remaining empties the mini-buffer."""
        mock_v = _make_mock_verifier()
        gate = _make_gate(mock_v, segment_sec=10.0)  # Very long segment so nothing triggers

        # Add a small chunk that won't fill the segment
        gate.add_chunk(_make_chunk(duration_sec=0.05), vad_confidence=0.9)
        assert gate._total_samples > 0

        gate.flush_remaining()
        assert gate._total_samples == 0
        assert len(gate._chunks) == 0

        gate.stop()

    def test_stop_halts_worker(self):
        """stop() signals the worker thread to terminate."""
        mock_v = _make_mock_verifier()
        gate = _make_gate(mock_v)

        assert gate._worker_thread.is_alive()
        gate.stop()
        time.sleep(0.2)
        assert not gate._worker_thread.is_alive()


# ---------------------------------------------------------------------------
# Recent events tracking
# ---------------------------------------------------------------------------

class TestRecentEvents:
    def test_recent_events_populated(self):
        """After processing segments, recent_events should have entries."""
        mock_v = _make_mock_verifier(verify_return=(True, 0.60))
        gate = _make_gate(mock_v, segment_sec=0.03)

        for _ in range(20):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.003)

        time.sleep(0.5)
        stats = gate.get_stats()

        if stats['total_segments'] > 0:
            events = stats['recent_events']
            assert len(events) > 0
            event = events[0]
            assert 'time' in event
            assert 'similarity' in event
            assert 'verified' in event
            assert 'duration' in event

        gate.stop()

    def test_recent_events_capped_at_20(self):
        """recent_events deque is capped at 20 entries."""
        mock_v = _make_mock_verifier(verify_return=(True, 0.60))
        gate = _make_gate(mock_v, segment_sec=0.02)

        # Feed lots of segments
        for _ in range(100):
            gate.add_chunk(_make_chunk(duration_sec=0.01), vad_confidence=0.9)
            time.sleep(0.002)

        time.sleep(1.0)
        stats = gate.get_stats()
        assert len(stats['recent_events']) <= 20

        gate.stop()
