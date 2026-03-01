"""
Score engine - derives wellness scores from DAM + acoustic features.

Next-gen scoring (v2):
  7 scores: Stress, Emotional Wellbeing, Calmness, Activation,
            Depression Risk, Anxiety Risk, Emotional Stability

  Retired: Energy (low validity 42/100), Burnout Risk (28/100), Resilience (28/100)

Two modes:
  Pre-calibration (<10 readings): population-level evidence-based formulas
  Post-calibration (>=10 readings): z-score personalized scoring via BaselineCalibrator

Includes:
  - Temporal smoothing (EMA) to prevent spurious zone transitions
  - Indeterminate zone handling for borderline readings
"""
import numpy as np
from typing import Dict, Optional
import app_config as config

# Population-level normalization constants for acoustic features
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
    # Next-gen feature norms
    'alpha_ratio_ref': -3.0,     # dB, typical speech
    'alpha_ratio_range': 10.0,   # dB range
    'mfcc3_ref': 0.0,            # centered
    'mfcc3_range': 20.0,
    'pitch_range_max': 200.0,    # Hz
    'rms_sd_max': 0.05,
    'hnr_max': 25.0,             # dB
    'h1_h2_ref': 5.0,            # dB typical
    'h1_h2_range': 15.0,
    'tremor_max': 0.3,           # proportion
    'pause_mean_ref': 0.5,       # seconds
    'pause_sd_max': 0.5,
    'phonation_max': 1.0,        # ratio
    'voice_breaks_max': 10,
}

# Score keys for EMA smoothing
SCORE_KEYS = [
    'stress_score', 'wellbeing_score', 'calm_score', 'activation_score',
    'depression_risk_score', 'anxiety_risk_score',
]


class ScoreEngine:
    def __init__(self, calibrator=None):
        self.calibrator = calibrator
        self._prev_smoothed: Optional[Dict[str, float]] = None
        self._ema_alpha = config.EMA_ALPHA

    def compute_scores(self, dam_output: Dict, acoustic_features: Dict) -> Dict:
        """
        Compute derived scores from DAM output and acoustic features.
        Returns dict with all 6 computed scores (emotional_stability added later by orchestrator).
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

        # Zone classification
        uncertainty_flag = dam_output.get('uncertainty_flag')
        anx_mapped = dam_output.get('anxiety_mapped', 0.0)
        zone = self._classify_zone(anx_mapped, smoothed['stress_score'], uncertainty_flag)

        result = {}
        for k in SCORE_KEYS:
            result[k] = smoothed[k]
            result[k.replace('_score', '_score_raw')] = raw_scores[k]

        # Backward compat: keep mood_score as alias for wellbeing_score
        result['mood_score'] = result['wellbeing_score']
        result['mood_score_raw'] = result['wellbeing_score_raw']
        # Backward compat: keep energy_score as alias for activation_score
        result['energy_score'] = result['activation_score']
        result['energy_score_raw'] = result['activation_score_raw']

        result['zone'] = zone
        return result

    def _apply_ema(self, raw: Dict[str, float]) -> Dict[str, float]:
        """Apply exponential moving average to score dimensions."""
        if self._prev_smoothed is None:
            self._prev_smoothed = {k: raw[k] for k in SCORE_KEYS}
            return {k: raw[k] for k in SCORE_KEYS}

        smoothed = {}
        alpha = self._ema_alpha
        for k in SCORE_KEYS:
            smoothed[k] = float(
                alpha * raw[k] + (1 - alpha) * self._prev_smoothed[k]
            )

        self._prev_smoothed = smoothed
        return smoothed

    # ------------------------------------------------------------------ #
    #  Population-level scoring (pre-calibration)
    # ------------------------------------------------------------------ #

    def _compute_population(self, dam: Dict, af: Dict) -> Dict:
        dep_mapped = dam.get('depression_mapped', 0.0)
        anx_mapped = dam.get('anxiety_mapped', 0.0)

        # Normalized DAM scores (0-100)
        norm_dep = min(100.0, (dep_mapped / 27.0) * 100.0)
        norm_anx = min(100.0, (anx_mapped / 21.0) * 100.0)

        # --- Extract and normalize all acoustic features ---
        f0_mean = max(0.0, af.get('f0_mean', 0.0))
        f0_std = max(0.0, af.get('f0_std', 0.0))
        rms = max(0.0, af.get('rms_energy', 0.0))
        speech_rate = max(0.0, af.get('speech_rate', 0.0))
        jitter = max(0.0, af.get('jitter', 0.0))
        shimmer = max(0.0, af.get('shimmer', 0.0))
        spectral_centroid = max(0.0, af.get('spectral_centroid', 0.0))
        spectral_entropy = max(0.0, af.get('spectral_entropy', 0.0))
        voice_breaks = max(0, af.get('voice_breaks', 0))

        # New features
        alpha_ratio = af.get('alpha_ratio', 0.0)
        mfcc3 = af.get('mfcc3', 0.0)
        pitch_range = max(0.0, af.get('pitch_range', 0.0))
        rms_sd = max(0.0, af.get('rms_sd', 0.0))
        phonation_ratio = max(0.0, af.get('phonation_ratio', 0.0))
        h1_h2 = af.get('h1_h2', 0.0)
        hnr = af.get('hnr', 0.0)
        voice_tremor = max(0.0, af.get('voice_tremor_index', 0.0))
        pause_mean = max(0.0, af.get('pause_mean', 0.0))
        pause_sd = max(0.0, af.get('pause_sd', 0.0))
        pause_rate = max(0.0, af.get('pause_rate', 0.0))

        # Normalize existing features to 0-100
        norm_f0_dev = min(100.0, abs(f0_mean - NORM['f0_mean_ref']) / NORM['f0_mean_ref'] * 100.0)
        norm_pitch_var = min(100.0, (f0_std / NORM['f0_std_max']) * 100.0)
        norm_rms = min(100.0, (rms / NORM['rms_max']) * 100.0)
        norm_speech_rate = min(100.0, (speech_rate / NORM['speech_rate_max']) * 100.0)
        speech_rate_dev = abs(speech_rate - NORM['speech_rate_ref'])
        norm_speech_rate_dev = min(100.0, (speech_rate_dev / 2.0) * 100.0)
        norm_jitter = min(100.0, (jitter / NORM['jitter_max']) * 100.0)
        norm_shimmer = min(100.0, (shimmer / NORM['shimmer_max']) * 100.0)
        norm_spectral_centroid = min(100.0, (spectral_centroid / NORM['spectral_centroid_max']) * 100.0)

        # Normalize new features to 0-100
        norm_alpha_ratio_dev = min(100.0, abs(alpha_ratio - NORM['alpha_ratio_ref']) / NORM['alpha_ratio_range'] * 100.0)
        norm_mfcc3_dev = min(100.0, abs(mfcc3 - NORM['mfcc3_ref']) / NORM['mfcc3_range'] * 100.0)
        norm_pitch_range = min(100.0, (pitch_range / NORM['pitch_range_max']) * 100.0)
        norm_rms_sd = min(100.0, (rms_sd / NORM['rms_sd_max']) * 100.0)
        norm_phonation = min(100.0, (phonation_ratio / NORM['phonation_max']) * 100.0)
        norm_hnr = min(100.0, max(0.0, (hnr / NORM['hnr_max']) * 100.0))
        norm_h1_h2 = min(100.0, max(0.0, ((h1_h2 - NORM['h1_h2_ref']) / NORM['h1_h2_range'] + 0.5) * 100.0))
        norm_tremor = min(100.0, (voice_tremor / NORM['tremor_max']) * 100.0)
        norm_pause_increase = min(100.0, (pause_mean / NORM['pause_mean_ref']) * 100.0)
        norm_pause_regularity = 100.0 - min(100.0, (pause_sd / NORM['pause_sd_max']) * 100.0)
        norm_pause_ratio = norm_pause_increase  # alias
        norm_voice_breaks = min(100.0, (voice_breaks / NORM['voice_breaks_max']) * 100.0)

        # Breathing regularity proxy (from pause regularity + pitch stability)
        norm_breathing_reg = (norm_pause_regularity + (100.0 - norm_pitch_var)) / 2.0

        # === STRESS v2 (7 features) ===
        stress = (
            0.25 * norm_anx +
            0.20 * norm_alpha_ratio_dev +
            0.15 * norm_f0_dev +
            0.15 * norm_pitch_var +
            0.10 * norm_pause_increase +
            0.08 * norm_jitter +
            0.07 * norm_mfcc3_dev
        )

        # === EMOTIONAL WELLBEING (replaces Mood) ===
        distress = 0.60 * norm_dep + 0.40 * norm_anx
        engagement = (norm_pitch_range + norm_rms_sd + norm_speech_rate + norm_phonation) / 4.0
        vitality = (norm_speech_rate + norm_phonation + norm_rms + norm_pitch_range) / 4.0
        wellbeing = 0.50 * (100.0 - distress) + 0.30 * engagement + 0.20 * vitality

        # === CALMNESS v2 (6 features, jitter bug FIXED) ===
        calm = (
            0.25 * (100.0 - norm_anx) +
            0.20 * norm_breathing_reg +
            0.20 * norm_h1_h2 +
            0.15 * norm_hnr +
            0.10 * norm_pause_regularity +
            0.10 * (100.0 - norm_pitch_var)
        )

        # === ACTIVATION (replaces Energy) ===
        activation = (
            0.25 * norm_rms +
            0.20 * min(100.0, f0_mean / 3.0) +   # norm f0 mean (0-300Hz → 0-100)
            0.20 * norm_pitch_range +
            0.15 * norm_speech_rate +
            0.10 * norm_spectral_centroid +
            0.10 * norm_rms_sd
        )

        # === DEPRESSION RISK (new) ===
        acoustic_dep = (
            0.20 * norm_jitter +
            0.20 * norm_shimmer +
            0.15 * norm_pitch_var +
            0.15 * norm_pause_ratio +
            0.15 * norm_speech_rate_dev +
            0.15 * norm_voice_breaks
        )
        depression_risk = 0.70 * norm_dep + 0.30 * acoustic_dep

        # === ANXIETY RISK (new) ===
        acoustic_anx = (
            0.30 * norm_tremor +
            0.25 * (100.0 - norm_h1_h2) +  # inverted: pressed voice = higher anxiety
            0.25 * norm_pitch_var +
            0.20 * min(100.0, pause_rate * 50.0)  # pauses/sec normalized
        )
        anxiety_risk = 0.70 * norm_anx + 0.30 * acoustic_anx

        return {
            'stress_score': float(np.clip(stress, 0, 100)),
            'wellbeing_score': float(np.clip(wellbeing, 0, 100)),
            'calm_score': float(np.clip(calm, 0, 100)),
            'activation_score': float(np.clip(activation, 0, 100)),
            'depression_risk_score': float(np.clip(depression_risk, 0, 100)),
            'anxiety_risk_score': float(np.clip(anxiety_risk, 0, 100)),
        }

    # ------------------------------------------------------------------ #
    #  Personalized scoring (post-calibration, z-score based)
    # ------------------------------------------------------------------ #

    def _compute_personalized(self, dam: Dict, af: Dict) -> Dict:
        cal = self.calibrator

        # Personalized DAM scores
        p_anx = cal.normalize_score('anxiety_mapped', dam.get('anxiety_mapped', 0.0))
        p_dep = cal.normalize_score('depression_mapped', dam.get('depression_mapped', 0.0))

        # Personalized acoustic features
        p_f0_mean = cal.normalize_score('f0_mean', af.get('f0_mean', 0.0))
        p_f0_std = cal.normalize_score('f0_std', af.get('f0_std', 0.0))
        p_rms = cal.normalize_score('rms_energy', af.get('rms_energy', 0.0))
        p_speech_rate = cal.normalize_score('speech_rate', af.get('speech_rate', 0.0))
        p_jitter = cal.normalize_score('jitter', af.get('jitter', 0.0))
        p_shimmer = cal.normalize_score('shimmer', af.get('shimmer', 0.0))
        p_spectral_centroid = cal.normalize_score('spectral_centroid', af.get('spectral_centroid', 0.0))

        # Personalized new features (fall back to population norm if not calibrated)
        p_alpha_ratio = cal.normalize_score('alpha_ratio', af.get('alpha_ratio', 0.0))
        p_mfcc3 = cal.normalize_score('mfcc3', af.get('mfcc3', 0.0))
        p_pitch_range = cal.normalize_score('pitch_range', af.get('pitch_range', 0.0))
        p_rms_sd = cal.normalize_score('rms_sd', af.get('rms_sd', 0.0))
        p_phonation = cal.normalize_score('phonation_ratio', af.get('phonation_ratio', 0.0))
        p_h1_h2 = cal.normalize_score('h1_h2', af.get('h1_h2', 0.0))
        p_hnr = cal.normalize_score('hnr', af.get('hnr', 0.0))
        p_tremor = cal.normalize_score('voice_tremor_index', af.get('voice_tremor_index', 0.0))
        p_pause_mean = cal.normalize_score('pause_mean', af.get('pause_mean', 0.0))
        p_pause_sd = cal.normalize_score('pause_sd', af.get('pause_sd', 0.0))
        p_voice_breaks = cal.normalize_score('voice_breaks', af.get('voice_breaks', 0))

        # Deviation from personal norms
        p_f0_dev = min(100.0, abs(p_f0_mean - 50.0) * 2.0)
        p_speech_rate_dev = min(100.0, abs(p_speech_rate - 50.0) * 2.0)
        p_alpha_dev = min(100.0, abs(p_alpha_ratio - 50.0) * 2.0)
        p_mfcc3_dev = min(100.0, abs(p_mfcc3 - 50.0) * 2.0)

        p_breathing_reg = ((100.0 - p_pause_sd) + (100.0 - p_f0_std)) / 2.0
        p_pause_regularity = 100.0 - p_pause_sd

        # === STRESS v2 (personalized) ===
        stress = (
            0.25 * p_anx +
            0.20 * p_alpha_dev +
            0.15 * p_f0_dev +
            0.15 * p_f0_std +
            0.10 * p_pause_mean +
            0.08 * p_jitter +
            0.07 * p_mfcc3_dev
        )

        # === EMOTIONAL WELLBEING (personalized) ===
        distress = 0.60 * p_dep + 0.40 * p_anx
        engagement = (p_pitch_range + p_rms_sd + p_speech_rate + p_phonation) / 4.0
        vitality = (p_speech_rate + p_phonation + p_rms + p_pitch_range) / 4.0
        wellbeing = 0.50 * (100.0 - distress) + 0.30 * engagement + 0.20 * vitality

        # === CALMNESS v2 (personalized) ===
        calm = (
            0.25 * (100.0 - p_anx) +
            0.20 * p_breathing_reg +
            0.20 * p_h1_h2 +
            0.15 * p_hnr +
            0.10 * p_pause_regularity +
            0.10 * (100.0 - p_f0_std)
        )

        # === ACTIVATION (personalized) ===
        activation = (
            0.25 * p_rms +
            0.20 * p_f0_mean +
            0.20 * p_pitch_range +
            0.15 * p_speech_rate +
            0.10 * p_spectral_centroid +
            0.10 * p_rms_sd
        )

        # === DEPRESSION RISK (personalized) ===
        acoustic_dep = (
            0.20 * p_jitter +
            0.20 * p_shimmer +
            0.15 * p_f0_std +
            0.15 * p_pause_mean +
            0.15 * p_speech_rate_dev +
            0.15 * p_voice_breaks
        )
        depression_risk = 0.70 * p_dep + 0.30 * acoustic_dep

        # === ANXIETY RISK (personalized) ===
        acoustic_anx = (
            0.30 * p_tremor +
            0.25 * (100.0 - p_h1_h2) +
            0.25 * p_f0_std +
            0.20 * p_pause_mean
        )
        anxiety_risk = 0.70 * p_anx + 0.30 * acoustic_anx

        return {
            'stress_score': float(np.clip(stress, 0, 100)),
            'wellbeing_score': float(np.clip(wellbeing, 0, 100)),
            'calm_score': float(np.clip(calm, 0, 100)),
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
        When uncertainty_flag is 'borderline', prefer the less severe zone.
        """
        if uncertainty_flag == 'borderline':
            if anxiety_mapped >= 12 or stress_score > config.STRESS_THRESHOLD_HIGH + 5:
                return 'stressed'
            elif anxiety_mapped >= 7 or stress_score > config.STRESS_THRESHOLD_MED + 10:
                return 'tense'
            elif anxiety_mapped < 3 and stress_score < 30:
                return 'calm'
            else:
                return 'steady'
        else:
            if anxiety_mapped >= 10 or stress_score > config.STRESS_THRESHOLD_HIGH:
                return 'stressed'
            elif anxiety_mapped >= 5 or stress_score > config.STRESS_THRESHOLD_MED:
                return 'tense'
            elif anxiety_mapped < 3 and stress_score < 30:
                return 'calm'
            else:
                return 'steady'
