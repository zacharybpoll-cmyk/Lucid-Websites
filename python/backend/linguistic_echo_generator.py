"""
Linguistic Echo Generator — surfaces the most notable linguistic feature
as a natural-language observation after each recording.

Only fires when a feature is meaningfully outside the user's baseline (|z| > 1.0).
Template-based, zero external dependencies, sub-millisecond generation.
"""
import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# Population-level fallback thresholds (mean, std) for pre-calibration use.
# Derived from normalization constants and typical speech ranges.
POPULATION_THRESHOLDS: Dict[str, Tuple[float, float]] = {
    'filler_rate':       (3.0, 2.0),     # per minute
    'hedging_score':     (1.5, 1.0),     # per minute
    'negative_sentiment': (0.08, 0.05),  # proportion
    'disfluency_rate':   (2.0, 1.5),     # per minute
    'lexical_diversity': (0.65, 0.12),   # type-token ratio
    'pronoun_i_ratio':   (0.06, 0.03),   # proportion
    'absolutist_ratio':  (0.02, 0.015),  # proportion
    'sentiment_valence': (0.1, 0.3),     # -1 to 1 scale
    'sentiment_arousal': (0.3, 0.2),     # 0 to 1 scale
    'semantic_coherence': (0.5, 0.15),   # 0 to 1 scale
}

# Template strings: feature -> (high_template, low_template)
# high = z > 1.0, low = z < -1.0
FEATURE_TEMPLATES: Dict[str, Tuple[str, str]] = {
    'filler_rate': (
        "More filler words than usual — often a sign of cognitive load.",
        "Fewer filler words than usual — clear, deliberate speech.",
    ),
    'hedging_score': (
        "More hedging language than your baseline — some extra caution in your thinking.",
        "Less hedging than usual — more decisive language today.",
    ),
    'negative_sentiment': (
        "Your language carried more negative tone than usual.",
        "More positive language than your baseline — lighter tone today.",
    ),
    'disfluency_rate': (
        "More speech disruptions than usual — can reflect divided attention.",
        "Smoother speech flow than your baseline today.",
    ),
    'lexical_diversity': (
        "Richer vocabulary than usual — broader expression today.",
        "Narrower vocabulary range than typical — can happen under pressure.",
    ),
    'pronoun_i_ratio': (
        "More self-referential language than usual — increased self-focus.",
        "Less self-referential language — more outward focus today.",
    ),
    'absolutist_ratio': (
        "More all-or-nothing phrasing than your norm.",
        "Less absolute language than usual — more nuanced expression.",
    ),
    'sentiment_valence': (
        "Your emotional tone leaned more positive than your baseline.",
        "Your emotional tone leaned more negative than your baseline.",
    ),
    'sentiment_arousal': (
        "Your speech carried higher emotional intensity than usual.",
        "Lower emotional intensity than your baseline — calmer expression.",
    ),
    'semantic_coherence': (
        "Your train of thought was more connected than usual.",
        "Your train of thought was less connected — sometimes reflects fatigue.",
    ),
}

# Features that are conceptually related (for compound echoes)
RELATED_PAIRS = {
    frozenset({'filler_rate', 'disfluency_rate'}): "cognitive load",
    frozenset({'negative_sentiment', 'sentiment_valence'}): "emotional tone",
    frozenset({'hedging_score', 'absolutist_ratio'}): "certainty",
    frozenset({'filler_rate', 'hedging_score'}): "uncertainty",
    frozenset({'pronoun_i_ratio', 'negative_sentiment'}): "self-critical focus",
}

Z_THRESHOLD = 1.0
COMPOUND_THRESHOLD = 1.5


class LinguisticEchoGenerator:
    """Generates natural-language observations from linguistic feature z-scores."""

    def generate_echo(self, linguistic_features: Dict, calibrator) -> Optional[str]:
        """
        Generate a linguistic echo from the most notable feature.

        Args:
            linguistic_features: Dict of feature_name -> value (already merged into acoustic_features)
            calibrator: BaselineCalibrator instance

        Returns:
            Echo string, or None if nothing exceeds threshold.
        """
        is_calibrated = calibrator is not None and calibrator.is_calibrated()

        # Compute z-scores for each linguistic feature
        scored = []
        for feature, templates in FEATURE_TEMPLATES.items():
            value = linguistic_features.get(feature)
            if value is None:
                continue

            z = self._compute_z(feature, value, calibrator, is_calibrated)
            if z is not None and abs(z) > Z_THRESHOLD:
                direction = 'high' if z > 0 else 'low'
                scored.append((feature, abs(z), z, direction))

        if not scored:
            return None

        # Sort by |z-score| descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Check for compound echo (top 2 both > 1.5 and related)
        if len(scored) >= 2 and scored[0][1] > COMPOUND_THRESHOLD and scored[1][1] > COMPOUND_THRESHOLD:
            pair = frozenset({scored[0][0], scored[1][0]})
            if pair in RELATED_PAIRS:
                echo = self._compound_echo(scored[0], scored[1])
                return self._add_framing(echo, is_calibrated)

        # Single echo from top feature
        top = scored[0]
        feature, _, z, direction = top
        idx = 0 if direction == 'high' else 1
        echo = FEATURE_TEMPLATES[feature][idx]
        return self._add_framing(echo, is_calibrated)

    def _compute_z(self, feature: str, value: float, calibrator, is_calibrated: bool) -> Optional[float]:
        """Compute z-score using personal baseline or population fallback."""
        if is_calibrated and calibrator is not None:
            baseline = calibrator.db.get_baseline(feature)
            if baseline and baseline.get('std', 0) > 0:
                return (value - baseline['mean']) / baseline['std']

        # Population fallback
        if feature in POPULATION_THRESHOLDS:
            mean, std = POPULATION_THRESHOLDS[feature]
            if std > 0:
                return (value - mean) / std

        return None

    def _compound_echo(self, feat1: tuple, feat2: tuple) -> str:
        """Generate a 2-sentence compound echo from related features."""
        f1_name, _, _, f1_dir = feat1
        f2_name, _, _, f2_dir = feat2
        idx1 = 0 if f1_dir == 'high' else 1
        idx2 = 0 if f2_dir == 'high' else 1
        return f"{FEATURE_TEMPLATES[f1_name][idx1]} {FEATURE_TEMPLATES[f2_name][idx2]}"

    def _add_framing(self, echo: str, is_calibrated: bool) -> str:
        """No framing prefix needed — templates are self-contained."""
        return echo
