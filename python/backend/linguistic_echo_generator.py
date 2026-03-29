"""
Linguistic Echo Generator — surfaces the most notable linguistic feature
as a natural-language observation after each recording.

Only fires when a feature is meaningfully outside the user's baseline (|z| > 1.0).
Template-based, zero external dependencies, sub-millisecond generation.
"""
import logging
import random
from typing import Optional, Dict, Tuple, List

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

# Template strings: feature -> (high_templates[], low_templates[])
# high = z > 1.0, low = z < -1.0
# Multiple variants per direction prevent repetitive echo text.
FEATURE_TEMPLATES: Dict[str, Tuple[List[str], List[str]]] = {
    'filler_rate': (
        [
            "More filler words than usual \u2014 often a sign of cognitive load.",
            "Your speech had extra filler words \u2014 your mind may be juggling more today.",
            "Higher filler rate than your baseline \u2014 a common marker of mental multitasking.",
        ],
        [
            "Fewer filler words than usual \u2014 clear, deliberate speech.",
            "Noticeably fewer filler words \u2014 your thoughts came out cleanly today.",
            "Your filler rate dropped below baseline \u2014 focused, intentional expression.",
        ],
    ),
    'hedging_score': (
        [
            "More hedging language than your baseline \u2014 some extra caution in your thinking.",
            "You hedged more than usual \u2014 weighing options more carefully today.",
            "Higher hedging detected \u2014 your language carried more qualifiers than normal.",
        ],
        [
            "Less hedging than usual \u2014 more decisive language today.",
            "Fewer qualifiers in your speech \u2014 you sounded more certain today.",
            "Your language was more direct than baseline \u2014 confident expression.",
        ],
    ),
    'negative_sentiment': (
        [
            "Your language carried more negative tone than usual.",
            "More negative phrasing than your norm \u2014 something may be weighing on you.",
            "Your word choices leaned heavier than baseline today.",
        ],
        [
            "More positive language than your baseline \u2014 lighter tone today.",
            "Your words carried a lighter feel than usual.",
            "Notably more positive phrasing \u2014 an upbeat shift from your baseline.",
        ],
    ),
    'disfluency_rate': (
        [
            "More speech disruptions than usual \u2014 can reflect divided attention.",
            "Your speech had more stumbles than baseline \u2014 your attention may be split.",
            "Higher disfluency rate today \u2014 often linked to cognitive load or distraction.",
        ],
        [
            "Smoother speech flow than your baseline today.",
            "Your speech flowed more smoothly than usual \u2014 clear mental state.",
            "Fewer disruptions in your speech \u2014 you were in a focused groove.",
        ],
    ),
    'lexical_diversity': (
        [
            "Richer vocabulary than usual \u2014 broader expression today.",
            "You drew from a wider word palette than your baseline.",
            "Higher lexical diversity \u2014 your language was more varied and expressive.",
        ],
        [
            "Narrower vocabulary range than typical \u2014 can happen under pressure.",
            "Your word choices were more repetitive than usual \u2014 sometimes a sign of stress.",
            "Lower lexical diversity today \u2014 your mind may be narrowing its focus.",
        ],
    ),
    'pronoun_i_ratio': (
        [
            "More self-referential language than usual \u2014 increased self-focus.",
            "You used 'I' more than baseline \u2014 a turn inward today.",
            "Higher first-person pronoun rate \u2014 your attention is directed inward.",
        ],
        [
            "Less self-referential language \u2014 more outward focus today.",
            "Fewer 'I' statements than your norm \u2014 your focus was external.",
            "Lower self-reference rate \u2014 you were thinking beyond yourself today.",
        ],
    ),
    'absolutist_ratio': (
        [
            "More all-or-nothing phrasing than your norm.",
            "Your language used more absolutes than usual \u2014 stronger convictions today.",
            "Higher absolutist language detected \u2014 you spoke in firmer terms.",
        ],
        [
            "Less absolute language than usual \u2014 more nuanced expression.",
            "Fewer absolutes in your speech \u2014 a more balanced tone today.",
            "Your phrasing was more measured than baseline \u2014 nuanced thinking.",
        ],
    ),
    'sentiment_valence': (
        [
            "Your emotional tone leaned more positive than your baseline.",
            "A more upbeat tone than usual \u2014 your words carried warmth.",
            "Your language had a brighter emotional quality today.",
        ],
        [
            "Your emotional tone leaned more negative than your baseline.",
            "A heavier emotional tone than usual in your language.",
            "Your words carried a more somber quality than your norm.",
        ],
    ),
    'sentiment_arousal': (
        [
            "Your speech carried higher emotional intensity than usual.",
            "More emotional energy in your voice today \u2014 heightened arousal.",
            "Your expression was more emotionally charged than baseline.",
        ],
        [
            "Lower emotional intensity than your baseline \u2014 calmer expression.",
            "Your speech was more emotionally even-keeled today.",
            "Less emotional charge in your words \u2014 a steadier state.",
        ],
    ),
    'semantic_coherence': (
        [
            "Your train of thought was more connected than usual.",
            "Higher coherence in your speech \u2014 ideas flowed logically.",
            "Your thoughts were more tightly linked than baseline today.",
        ],
        [
            "Your train of thought was less connected \u2014 sometimes reflects fatigue.",
            "Lower coherence detected \u2014 your thoughts jumped around more than usual.",
            "Your ideas were less linked than baseline \u2014 may indicate tiredness.",
        ],
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

Z_THRESHOLD = 2.0
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
        templates = FEATURE_TEMPLATES[feature][idx]
        echo = random.choice(templates)
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
        return f"{random.choice(FEATURE_TEMPLATES[f1_name][idx1])} {random.choice(FEATURE_TEMPLATES[f2_name][idx2])}"

    def _add_framing(self, echo: str, is_calibrated: bool) -> str:
        """No framing prefix needed — templates are self-contained."""
        return echo
