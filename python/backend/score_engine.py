"""
Score engine - derives stress, mood, energy, calm scores from DAM + acoustic features.

Two modes:
  Pre-calibration (<10 readings): population-level evidence-based formulas
  Post-calibration (>=10 readings): z-score personalized scoring via BaselineCalibrator

Includes:
  - Temporal smoothing (EMA) to prevent spurious zone transitions
  - Shimmer integration in mood formula
  - Indeterminate zone handling for borderline readings
"""
import numpy as np
from typing import Dict, Optional
import app_config as config

# Population-level normalization constants for acoustic features
# Used before personal baseline is established
NORM = {
    'f0_mean_ref': 180.0,        # Hz, gender-neutral average
    'f0_std_max': 50.0,          # Hz, typical max variability
    'rms_max': 0.1,              # Typical max RMS energy
    'speech_rate_ref': 4.0,      # syl/sec baseline
    'speech_rate_max': 6.0,      # syl/sec max for normalization
    'jitter_max': 0.05,          # Typical max jitter
    'shimmer_max': 0.5,          # Typical max shimmer (relative)
    'spectral_centroid_max': 4000.0,  # Hz
    'spectral_entropy_max': 5.0,      # Bits
}


class ScoreEngine:
    def __init__(self, calibrator=None):
        """
        Args:
            calibrator: BaselineCalibrator instance for personalized scoring
        """
        self.calibrator = calibrator

        # EMA state for temporal smoothing (Step 3)
        self._prev_smoothed: Optional[Dict[str, float]] = None
        self._ema_alpha = config.EMA_ALPHA

    def compute_scores(self, dam_output: Dict, acoustic_features: Dict) -> Dict:
        """
        Compute derived scores from DAM output and acoustic features.
        Applies temporal smoothing (EMA) to prevent spurious zone transitions.

        Args:
            dam_output: Dict with depression_mapped, anxiety_mapped, CIs, flags, etc.
            acoustic_features: Dict with f0_mean, f0_std, rms_energy, shimmer, etc.

        Returns:
            Dict with stress_score, mood_score, energy_score, calm_score, zone,
                  and smoothed variants.
        """
        use_personal = (
            self.calibrator is not None
            and self.calibrator.is_calibrated()
        )

        if use_personal:
            raw_scores = self._compute_personalized(dam_output, acoustic_features)
        else:
            raw_scores = self._compute_population(dam_output, acoustic_features)

        # Apply temporal smoothing (EMA)
        smoothed = self._apply_ema(raw_scores)

        # Zone classification uses smoothed scores
        # For borderline readings (Step 7), prefer less severe zone
        uncertainty_flag = dam_output.get('uncertainty_flag')
        anx_mapped = dam_output.get('anxiety_mapped', 0.0)
        zone = self._classify_zone(anx_mapped, smoothed['stress_score'], uncertainty_flag)

        return {
            'stress_score': smoothed['stress_score'],
            'mood_score': smoothed['mood_score'],
            'energy_score': smoothed['energy_score'],
            'calm_score': smoothed['calm_score'],
            'wellbeing_score': smoothed['wellbeing_score'],
            'activation_score': smoothed['activation_score'],
            'depression_risk_score': smoothed['depression_risk_score'],
            'anxiety_risk_score': smoothed['anxiety_risk_score'],
            'stress_score_raw': raw_scores['stress_score'],
            'mood_score_raw': raw_scores['mood_score'],
            'energy_score_raw': raw_scores['energy_score'],
            'calm_score_raw': raw_scores['calm_score'],
            'wellbeing_score_raw': raw_scores['wellbeing_score'],
            'activation_score_raw': raw_scores['activation_score'],
            'depression_risk_score_raw': raw_scores['depression_risk_score'],
            'anxiety_risk_score_raw': raw_scores['anxiety_risk_score'],
            'zone': zone,
        }

    def _apply_ema(self, raw: Dict[str, float]) -> Dict[str, float]:
        """Apply exponential moving average to score dimensions."""
        score_keys = ['stress_score', 'mood_score', 'energy_score', 'calm_score',
                      'wellbeing_score', 'activation_score', 'depression_risk_score',
                      'anxiety_risk_score']

        if self._prev_smoothed is None:
            # First reading: no smoothing
            self._prev_smoothed = {k: raw[k] for k in score_keys}
            return {k: raw[k] for k in score_keys}

        smoothed = {}
        alpha = self._ema_alpha
        for k in score_keys:
            smoothed[k] = float(
                alpha * raw[k] + (1 - alpha) * self._prev_smoothed[k]
            )

        self._prev_smoothed = smoothed
        return smoothed

    # ------------------------------------------------------------------ #
    #  Population-level scoring (pre-calibration)
    # ------------------------------------------------------------------ #

    def _compute_population(self, dam: Dict, af: Dict) -> Dict:
        # Mapped clinical scores from DAM (via isotonic regression)
        dep_mapped = dam.get('depression_mapped', 0.0)
        anx_mapped = dam.get('anxiety_mapped', 0.0)

        # Normalized DAM scores (0-100)
        norm_dep = min(100.0, (dep_mapped / 27.0) * 100.0)
        norm_anx = min(100.0, (anx_mapped / 21.0) * 100.0)

        # Acoustic features (safe extraction with defaults)
        f0_mean = max(0.0, af.get('f0_mean', 0.0))
        f0_std = max(0.0, af.get('f0_std', 0.0))
        rms = max(0.0, af.get('rms_energy', 0.0))
        speech_rate = max(0.0, af.get('speech_rate', 0.0))
        jitter = max(0.0, af.get('jitter', 0.0))
        shimmer = max(0.0, af.get('shimmer', 0.0))
        spectral_centroid = max(0.0, af.get('spectral_centroid', 0.0))
        spectral_entropy = max(0.0, af.get('spectral_entropy', 0.0))

        # Normalize acoustic features to 0-100
        norm_f0_dev = min(100.0, abs(f0_mean - NORM['f0_mean_ref']) / NORM['f0_mean_ref'] * 100.0)
        norm_pitch_var = min(100.0, (f0_std / NORM['f0_std_max']) * 100.0)
        norm_rms = min(100.0, (rms / NORM['rms_max']) * 100.0)
        norm_speech_rate = min(100.0, (speech_rate / NORM['speech_rate_max']) * 100.0)
        speech_rate_dev = abs(speech_rate - NORM['speech_rate_ref'])
        norm_speech_rate_dev = min(100.0, (speech_rate_dev / 2.0) * 100.0)
        norm_jitter = min(100.0, (jitter / NORM['jitter_max']) * 100.0)
        norm_shimmer = min(100.0, (shimmer / NORM['shimmer_max']) * 100.0)
        norm_spectral_centroid = min(100.0, (spectral_centroid / NORM['spectral_centroid_max']) * 100.0)
        norm_spectral_entropy = min(100.0, (spectral_entropy / NORM['spectral_entropy_max']) * 100.0)

        # Pitch range as dynamics indicator (same as pitch var for now)
        norm_pitch_range = norm_pitch_var

        # === STRESS ===
        # 6 features, evidence-based weights
        # Sources: Stenberg 2025 (F0 meta-analysis), PLOS ONE 2025 (69 prosodic features)
        stress = (
            0.35 * norm_anx +
            0.20 * norm_f0_dev +
            0.18 * norm_pitch_var +
            0.12 * norm_jitter +
            0.10 * norm_speech_rate_dev +
            0.05 * norm_spectral_centroid
        )

        # === MOOD ===
        # DAM-driven + shimmer (depression biomarker, Cummins 2015)
        # Shimmer inverted: higher shimmer -> lower mood
        mood = 100.0 - (0.55 * norm_dep + 0.35 * norm_anx + 0.10 * norm_shimmer)

        # === ENERGY ===
        # Acoustic-driven (arousal dimension, well-captured by acoustics)
        depression_modifier = 1.0 - dep_mapped / 54.0  # halves at PHQ-9 max (27)
        depression_modifier = max(0.5, min(1.0, depression_modifier))

        energy_base = (
            0.30 * norm_rms +
            0.25 * norm_speech_rate +
            0.20 * norm_pitch_range +
            0.15 * (100.0 - norm_spectral_entropy) +  # clarity (inverted)
            0.10 * (depression_modifier * 100.0)
        )
        energy = energy_base

        # === CALM ===
        # Distinct from inverse-stress
        speech_rate_steadiness = 100.0 - norm_speech_rate_dev

        calm = (
            0.30 * (100.0 - norm_anx) +
            0.25 * (100.0 - norm_pitch_var) +
            0.15 * norm_jitter +  # jitter increases in relaxed states
            0.15 * speech_rate_steadiness +
            0.15 * (100.0 - norm_spectral_entropy)
        )

        # === WELLBEING === (positive affect: low depression + low anxiety + voice quality)
        # Distinct from mood by emphasizing positive markers and voice quality
        wellbeing = (
            0.35 * (100.0 - norm_dep) +
            0.25 * (100.0 - norm_anx) +
            0.15 * (100.0 - norm_shimmer) +
            0.15 * norm_speech_rate +
            0.10 * (100.0 - norm_jitter)
        )

        # === ACTIVATION === (arousal/engagement: acoustic dynamics)
        # Distinct from energy by emphasizing variation and dynamism
        activation = (
            0.30 * norm_rms +
            0.25 * norm_pitch_range +
            0.20 * norm_speech_rate +
            0.15 * norm_spectral_centroid +
            0.10 * (100.0 - norm_spectral_entropy)
        )

        # === DEPRESSION RISK === (0-100 from mapped PHQ-9 score)
        depression_risk = min(100.0, (dep_mapped / 27.0) * 100.0)

        # === ANXIETY RISK === (0-100 from mapped GAD-7 score)
        anxiety_risk = min(100.0, (anx_mapped / 21.0) * 100.0)

        return {
            'stress_score': float(np.clip(stress, 0, 100)),
            'mood_score': float(np.clip(mood, 0, 100)),
            'energy_score': float(np.clip(energy, 0, 100)),
            'calm_score': float(np.clip(calm, 0, 100)),
            'wellbeing_score': float(np.clip(wellbeing, 0, 100)),
            'activation_score': float(np.clip(activation, 0, 100)),
            'depression_risk_score': float(np.clip(depression_risk, 0, 100)),
            'anxiety_risk_score': float(np.clip(anxiety_risk, 0, 100)),
        }

    # ------------------------------------------------------------------ #
    #  Personalized scoring (post-calibration, z-score based)
    # ------------------------------------------------------------------ #

    def _compute_personalized(self, dam: Dict, af: Dict) -> Dict:
        cal = self.calibrator

        # Personalize each feature: z-score against personal baseline -> 0-100
        p_anx = cal.normalize_score('anxiety_mapped', dam.get('anxiety_mapped', 0.0))
        p_dep = cal.normalize_score('depression_mapped', dam.get('depression_mapped', 0.0))

        p_f0_mean = cal.normalize_score('f0_mean', af.get('f0_mean', 0.0))
        p_f0_std = cal.normalize_score('f0_std', af.get('f0_std', 0.0))
        p_rms = cal.normalize_score('rms_energy', af.get('rms_energy', 0.0))
        p_speech_rate = cal.normalize_score('speech_rate', af.get('speech_rate', 0.0))
        p_jitter = cal.normalize_score('jitter', af.get('jitter', 0.0))
        p_shimmer = cal.normalize_score('shimmer', af.get('shimmer', 0.0))
        p_spectral_centroid = cal.normalize_score('spectral_centroid', af.get('spectral_centroid', 0.0))
        p_spectral_entropy = cal.normalize_score('spectral_entropy', af.get('spectral_entropy', 0.0))

        # F0 deviation: how far from YOUR normal pitch
        p_f0_dev = abs(p_f0_mean - 50.0) * 2.0  # 50 = your average; deviation scaled to 0-100
        p_f0_dev = min(100.0, p_f0_dev)

        # Speech rate deviation from YOUR normal
        p_speech_rate_dev = abs(p_speech_rate - 50.0) * 2.0
        p_speech_rate_dev = min(100.0, p_speech_rate_dev)

        # === STRESS (personalized) ===
        stress = (
            0.35 * p_anx +
            0.20 * p_f0_dev +
            0.18 * p_f0_std +
            0.12 * p_jitter +
            0.10 * p_speech_rate_dev +
            0.05 * p_spectral_centroid
        )

        # === MOOD (personalized, with shimmer) ===
        mood = 100.0 - (0.55 * p_dep + 0.35 * p_anx + 0.10 * p_shimmer)

        # === ENERGY (personalized) ===
        depression_modifier = max(0.5, 1.0 - (p_dep / 200.0))
        energy = (
            0.30 * p_rms +
            0.25 * p_speech_rate +
            0.20 * p_f0_std +
            0.15 * (100.0 - p_spectral_entropy) +
            0.10 * (depression_modifier * 100.0)
        )

        # === CALM (personalized) ===
        speech_rate_steadiness = 100.0 - p_speech_rate_dev
        calm = (
            0.30 * (100.0 - p_anx) +
            0.25 * (100.0 - p_f0_std) +
            0.15 * p_jitter +
            0.15 * speech_rate_steadiness +
            0.15 * (100.0 - p_spectral_entropy)
        )

        # === WELLBEING (personalized) ===
        wellbeing = (
            0.35 * (100.0 - p_dep) +
            0.25 * (100.0 - p_anx) +
            0.15 * (100.0 - p_shimmer) +
            0.15 * p_speech_rate +
            0.10 * (100.0 - p_jitter)
        )

        # === ACTIVATION (personalized) ===
        activation = (
            0.30 * p_rms +
            0.25 * p_f0_std +
            0.20 * p_speech_rate +
            0.15 * p_spectral_centroid +
            0.10 * (100.0 - p_spectral_entropy)
        )

        # === DEPRESSION RISK (personalized) ===
        dep_mapped = dam.get('depression_mapped', 0.0)
        depression_risk = min(100.0, max(0.0, dep_mapped / 27.0 * 100.0))

        # === ANXIETY RISK (personalized) ===
        anx_mapped = dam.get('anxiety_mapped', 0.0)
        anxiety_risk = min(100.0, max(0.0, anx_mapped / 21.0 * 100.0))

        return {
            'stress_score': float(np.clip(stress, 0, 100)),
            'mood_score': float(np.clip(mood, 0, 100)),
            'energy_score': float(np.clip(energy, 0, 100)),
            'calm_score': float(np.clip(calm, 0, 100)),
            'wellbeing_score': float(np.clip(wellbeing, 0, 100)),
            'activation_score': float(np.clip(activation, 0, 100)),
            'depression_risk_score': float(np.clip(depression_risk, 0, 100)),
            'anxiety_risk_score': float(np.clip(anxiety_risk, 0, 100)),
        }

    # ------------------------------------------------------------------ #
    #  Zone classification
    # ------------------------------------------------------------------ #

    def _classify_zone(self, anxiety_mapped: float, stress_score: float,
                       uncertainty_flag: Optional[str] = None) -> str:
        """
        Classify current state using mapped GAD-7 scores (0-21 scale).

        GAD-7 thresholds: 0-4 minimal, 5-9 mild, 10-14 moderate, 15-21 severe

        When uncertainty_flag is 'borderline', prefer the less severe zone.
        """
        if uncertainty_flag == 'borderline':
            # Shift thresholds up to prefer less severe zone
            if anxiety_mapped >= 12 or stress_score > 75:
                return 'stressed'
            elif anxiety_mapped >= 7 or stress_score > 50:
                return 'tense'
            elif anxiety_mapped < 3 and stress_score < 30:
                return 'calm'
            else:
                return 'steady'
        else:
            if anxiety_mapped >= 10 or stress_score > 70:
                return 'stressed'
            elif anxiety_mapped >= 5 or stress_score > 40:
                return 'tense'
            elif anxiety_mapped < 3 and stress_score < 30:
                return 'calm'
            else:
                return 'steady'
