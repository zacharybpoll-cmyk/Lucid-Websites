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
    'alpha_ratio_ref': 5.0,      # dB, typical relaxed alpha ratio
    'alpha_ratio_max': 20.0,     # dB, normalization ceiling
    'mfcc3_ref': 0.0,            # Centered reference
    'mfcc3_max': 30.0,           # Typical MFCC3 range
    'hnr_ref': 20.0,             # dB, typical healthy HNR
    'hnr_max': 40.0,             # dB, normalization ceiling
    # Phase 1: Formants
    'f1_ref': 500.0,             # Hz, typical F1 (mid vowel)
    'f1_max': 900.0,             # Hz, elevated F1 → vocal strain
    'f2_ref': 1500.0,            # Hz, typical F2
    'f2_max': 2500.0,            # Hz
    # Phase 1: Spectral flux
    'spectral_flux_max': 0.05,   # Typical max flux (normalized spectrum)
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
        zone = self._classify_zone(anx_mapped, smoothed['stress_score'], uncertainty_flag, smoothed['calm_score'])

        # Zone confidence (Tier 4c)
        zone_confidence = self._compute_zone_confidence(
            dam_output, acoustic_features, smoothed['stress_score']
        )

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
            'zone_confidence': zone_confidence,
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
        alpha_ratio = af.get('alpha_ratio', 0.0)
        mfcc3 = af.get('mfcc3', 0.0)
        hnr = max(0.0, af.get('hnr', 0.0))
        # Phase 1: new acoustic features
        f1_mean = max(0.0, af.get('f1_mean', 0.0))
        f2_mean = max(0.0, af.get('f2_mean', 0.0))
        spectral_flux = max(0.0, af.get('spectral_flux', 0.0))

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

        # New feature normalization
        # Alpha ratio: deviation from relaxed baseline (lower = more tense)
        alpha_ratio_dev = max(0.0, NORM['alpha_ratio_ref'] - alpha_ratio)
        norm_alpha_ratio_dev = min(100.0, (alpha_ratio_dev / NORM['alpha_ratio_max']) * 100.0)
        # MFCC3: negative deviation from 0 indicates stress (lower = more cortisol)
        mfcc3_stress = max(0.0, -mfcc3)  # Negative MFCC3 = stress
        norm_mfcc3_dev = min(100.0, (mfcc3_stress / NORM['mfcc3_max']) * 100.0)
        # HNR: lower = noisier voice = more stress (inverted for stress)
        norm_hnr = min(100.0, (hnr / NORM['hnr_max']) * 100.0)
        # F1 elevation: higher F1 → more vocal tension/stress (Protopapas & Lieberman 1997)
        f1_elevation = max(0.0, f1_mean - NORM['f1_ref']) if f1_mean > 0 else 0.0
        norm_f1_elevation = min(100.0, (f1_elevation / (NORM['f1_max'] - NORM['f1_ref'])) * 100.0)
        # Spectral flux: higher flux → more dynamic speech (arousal indicator)
        norm_spectral_flux = min(100.0, (spectral_flux / NORM['spectral_flux_max']) * 100.0)

        # Linguistic features (from Whisper transcription, 0 if unavailable)
        filler_rate = max(0.0, af.get('filler_rate', 0.0))
        hedging_score = max(0.0, af.get('hedging_score', 0.0))
        negative_sentiment = max(0.0, af.get('negative_sentiment', 0.0))
        disfluency_rate = max(0.0, af.get('disfluency_rate', 0.0))

        # Normalize linguistic features to 0-100
        # Filler rate: 0-20 fillers/min → 0-100 (20/min is very high)
        norm_filler_rate = min(100.0, (filler_rate / 20.0) * 100.0)
        # Hedging: 0-15 hedges/min → 0-100
        norm_hedging = min(100.0, (hedging_score / 15.0) * 100.0)
        # Negative sentiment: 0-0.15 ratio → 0-100 (15% negative words is very high)
        norm_negative_sentiment = min(100.0, (negative_sentiment / 0.15) * 100.0)
        # Disfluency: 0-10 per min → 0-100
        norm_disfluency = min(100.0, (disfluency_rate / 10.0) * 100.0)

        # Check if linguistic features are available (non-zero = Whisper ran)
        has_linguistic = (filler_rate > 0 or hedging_score > 0
                         or negative_sentiment > 0 or disfluency_rate > 0)

        # Phase 2: enhanced linguistic features
        pronoun_i_ratio = max(0.0, af.get('pronoun_i_ratio', 0.0))
        absolutist_ratio = max(0.0, af.get('absolutist_ratio', 0.0))
        sentiment_valence = af.get('sentiment_valence', 0.0)  # -1 to +1
        sentiment_arousal = max(0.0, af.get('sentiment_arousal', 0.0))  # 0 to 1

        # Normalize Phase 2 features to 0-100
        # Pronoun I ratio: 0-0.15 → 0-100 (15% = clinically elevated)
        norm_pronoun_i = min(100.0, (pronoun_i_ratio / 0.15) * 100.0)
        # Absolutist ratio: 0-0.10 → 0-100
        norm_absolutist = min(100.0, (absolutist_ratio / 0.10) * 100.0)
        # Sentiment valence: -1 to +1 → invert to stress contribution (negative = stressed)
        # valence -1 → 100 stress, valence +1 → 0 stress
        norm_valence_stress = min(100.0, max(0.0, (-sentiment_valence + 1.0) / 2.0 * 100.0))
        # Sentiment arousal: 0 to 1 → 0-100 (directly maps to activation)
        norm_sentiment_arousal = min(100.0, sentiment_arousal * 100.0)

        # Pitch range as dynamics indicator (same as pitch var for now)
        norm_pitch_range = norm_pitch_var

        # === STRESS ===
        # Evidence-aligned weights (v2 audit, March 2026)
        # Two formulas: with and without linguistic features (graceful degradation)
        # Jitter REMOVED — unreliable for stress detection (Veiga et al. 2025).
        # Alpha ratio ADDED — most reliable speech stress marker (Menne et al. 2025).
        # MFCC3 ADDED — cortisol association (beta=-0.606, p=0.014).
        if has_linguistic:
            # Full formula: 43% DAM, 19% acoustic, 15% P1 spectral, 23% linguistic
            stress = (
                0.43 * norm_anx +                  # DAM anxiety (most validated)
                0.07 * norm_f0_dev +                # F0 deviation
                0.05 * norm_pitch_var +             # Pitch variability
                0.04 * norm_speech_rate_dev +        # Speech rate deviation
                0.08 * norm_alpha_ratio_dev +        # Alpha ratio (Menne 2025)
                0.05 * norm_mfcc3_dev +              # MFCC3 (cortisol)
                0.02 * norm_f1_elevation +           # F1 elevation (vocal tension)
                0.07 * norm_filler_rate +             # Fillers (cognitive load)
                0.05 * norm_hedging +                 # Hedging (uncertainty)
                0.04 * norm_negative_sentiment +      # Negative affect
                0.03 * norm_disfluency +              # Disfluencies (cognitive load)
                0.04 * norm_valence_stress +          # Sentiment valence (negative = stress)
                0.03 * norm_absolutist               # Absolutist language
            )
        else:
            # Fallback: acoustic-only (no Whisper available)
            stress = (
                0.53 * norm_anx +                  # DAM anxiety (boosted without linguistic)
                0.11 * norm_f0_dev +                # F0 deviation
                0.07 * norm_pitch_var +             # Pitch variability
                0.08 * norm_speech_rate_dev +        # Speech rate deviation
                0.08 * norm_alpha_ratio_dev +        # Alpha ratio
                0.06 * norm_mfcc3_dev +              # MFCC3
                0.04 * norm_f1_elevation +           # F1 elevation
                0.03 * norm_spectral_centroid        # Spectral centroid
            )

        # === MOOD ===
        # DAM-driven + shimmer (depression biomarker, Cummins 2015)
        # Phase 2: pronoun_i_ratio + absolutist_ratio add depression signal
        # Shimmer inverted: higher shimmer -> lower mood
        if has_linguistic:
            mood = 100.0 - (
                0.48 * norm_dep +
                0.30 * norm_anx +
                0.08 * norm_shimmer +
                0.07 * norm_pronoun_i +    # High self-focus (Rude et al. 2004)
                0.04 * norm_absolutist +    # Absolutist thinking
                0.03 * norm_valence_stress  # Negative sentiment contribution
            )
        else:
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
        # Jitter removed (contradictory evidence). HNR added (higher = clearer/calmer voice).
        # Sentiment valence: positive valence → calmer; negative arousal → calmer
        speech_rate_steadiness = 100.0 - norm_speech_rate_dev

        if has_linguistic:
            calm = (
                0.27 * (100.0 - norm_anx) +
                0.22 * (100.0 - norm_pitch_var) +
                0.13 * norm_hnr +                       # HNR: cleaner voice = calmer
                0.13 * speech_rate_steadiness +
                0.12 * (100.0 - norm_spectral_entropy) +
                0.07 * (100.0 - norm_valence_stress) +  # Positive valence = calmer
                0.06 * (100.0 - norm_sentiment_arousal) # Low arousal = calmer
            )
        else:
            calm = (
                0.30 * (100.0 - norm_anx) +
                0.25 * (100.0 - norm_pitch_var) +
                0.15 * norm_hnr +
                0.15 * speech_rate_steadiness +
                0.15 * (100.0 - norm_spectral_entropy)
            )

        # === WELLBEING === (positive affect: low depression + low anxiety + voice quality)
        # HNR replaces jitter as voice quality indicator
        wellbeing = (
            0.35 * (100.0 - norm_dep) +
            0.25 * (100.0 - norm_anx) +
            0.15 * (100.0 - norm_shimmer) +
            0.15 * norm_speech_rate +
            0.10 * norm_hnr                     # HNR: clearer voice = better wellbeing
        )

        # === ACTIVATION === (arousal/engagement: acoustic dynamics)
        # Phase 1: spectral_flux adds dynamism signal
        # Phase 2: sentiment_arousal adds affective arousal
        if has_linguistic:
            activation = (
                0.25 * norm_rms +
                0.22 * norm_pitch_range +
                0.18 * norm_speech_rate +
                0.13 * norm_spectral_centroid +
                0.08 * (100.0 - norm_spectral_entropy) +
                0.08 * norm_spectral_flux +         # Spectral flux (speech dynamism)
                0.06 * norm_sentiment_arousal        # Affective arousal
            )
        else:
            activation = (
                0.27 * norm_rms +
                0.23 * norm_pitch_range +
                0.20 * norm_speech_rate +
                0.15 * norm_spectral_centroid +
                0.08 * (100.0 - norm_spectral_entropy) +
                0.07 * norm_spectral_flux            # Spectral flux
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
        p_shimmer = cal.normalize_score('shimmer', af.get('shimmer', 0.0))
        p_spectral_centroid = cal.normalize_score('spectral_centroid', af.get('spectral_centroid', 0.0))
        p_spectral_entropy = cal.normalize_score('spectral_entropy', af.get('spectral_entropy', 0.0))
        p_alpha_ratio = cal.normalize_score('alpha_ratio', af.get('alpha_ratio', 0.0))
        p_mfcc3 = cal.normalize_score('mfcc3', af.get('mfcc3', 0.0))
        p_hnr = cal.normalize_score('hnr', af.get('hnr', 0.0))

        # F0 deviation: how far from YOUR normal pitch
        p_f0_dev = abs(p_f0_mean - 50.0) * 2.0  # 50 = your average; deviation scaled to 0-100
        p_f0_dev = min(100.0, p_f0_dev)

        # Speech rate deviation from YOUR normal
        p_speech_rate_dev = abs(p_speech_rate - 50.0) * 2.0
        p_speech_rate_dev = min(100.0, p_speech_rate_dev)

        # Alpha ratio deviation from personal baseline (lower = more tense)
        p_alpha_dev = max(0.0, (50.0 - p_alpha_ratio) * 2.0)
        p_alpha_dev = min(100.0, p_alpha_dev)

        # MFCC3 deviation (lower than personal baseline = more stress)
        p_mfcc3_dev = max(0.0, (50.0 - p_mfcc3) * 2.0)
        p_mfcc3_dev = min(100.0, p_mfcc3_dev)

        # Phase 1: personalized formants + spectral flux
        p_f1 = cal.normalize_score('f1_mean', af.get('f1_mean', 0.0))
        p_spectral_flux = cal.normalize_score('spectral_flux', af.get('spectral_flux', 0.0))
        # F1 elevation: above YOUR normal = more tension
        p_f1_elevation = max(0.0, (p_f1 - 50.0) * 2.0)
        p_f1_elevation = min(100.0, p_f1_elevation)

        # Linguistic features (personalized z-scores)
        p_filler = cal.normalize_score('filler_rate', af.get('filler_rate', 0.0))
        p_hedging = cal.normalize_score('hedging_score', af.get('hedging_score', 0.0))
        p_neg_sent = cal.normalize_score('negative_sentiment', af.get('negative_sentiment', 0.0))
        p_disfluency = cal.normalize_score('disfluency_rate', af.get('disfluency_rate', 0.0))

        # Phase 2: enhanced linguistic features (personalized)
        p_pronoun_i = cal.normalize_score('pronoun_i_ratio', af.get('pronoun_i_ratio', 0.0))
        p_absolutist = cal.normalize_score('absolutist_ratio', af.get('absolutist_ratio', 0.0))
        sentiment_valence = af.get('sentiment_valence', 0.0)
        sentiment_arousal = af.get('sentiment_arousal', 0.0)
        # Valence: map -1/+1 to stress contribution (no personal baseline for this)
        p_valence_stress = min(100.0, max(0.0, (-sentiment_valence + 1.0) / 2.0 * 100.0))
        p_sentiment_arousal = min(100.0, sentiment_arousal * 100.0)

        has_linguistic = (af.get('filler_rate', 0.0) > 0 or af.get('hedging_score', 0.0) > 0
                         or af.get('negative_sentiment', 0.0) > 0 or af.get('disfluency_rate', 0.0) > 0)

        # === STRESS (personalized, evidence-aligned v2 + Phase 1/2) ===
        if has_linguistic:
            stress = (
                0.43 * p_anx +
                0.07 * p_f0_dev +
                0.05 * p_f0_std +
                0.04 * p_speech_rate_dev +
                0.08 * p_alpha_dev +
                0.05 * p_mfcc3_dev +
                0.02 * p_f1_elevation +
                0.07 * p_filler +
                0.05 * p_hedging +
                0.04 * p_neg_sent +
                0.03 * p_disfluency +
                0.04 * p_valence_stress +
                0.03 * p_absolutist
            )
        else:
            # Fallback: acoustic-only
            stress = (
                0.53 * p_anx +
                0.11 * p_f0_dev +
                0.07 * p_f0_std +
                0.08 * p_speech_rate_dev +
                0.08 * p_alpha_dev +
                0.06 * p_mfcc3_dev +
                0.04 * p_f1_elevation +
                0.03 * p_spectral_centroid
            )

        # === MOOD (personalized, with shimmer + Phase 2) ===
        if has_linguistic:
            mood = 100.0 - (
                0.48 * p_dep +
                0.30 * p_anx +
                0.08 * p_shimmer +
                0.07 * p_pronoun_i +
                0.04 * p_absolutist +
                0.03 * p_valence_stress
            )
        else:
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

        # === CALM (personalized, HNR + Phase 2 valence/arousal) ===
        speech_rate_steadiness = 100.0 - p_speech_rate_dev
        if has_linguistic:
            calm = (
                0.27 * (100.0 - p_anx) +
                0.22 * (100.0 - p_f0_std) +
                0.13 * p_hnr +
                0.13 * speech_rate_steadiness +
                0.12 * (100.0 - p_spectral_entropy) +
                0.07 * (100.0 - p_valence_stress) +
                0.06 * (100.0 - p_sentiment_arousal)
            )
        else:
            calm = (
                0.30 * (100.0 - p_anx) +
                0.25 * (100.0 - p_f0_std) +
                0.15 * p_hnr +
                0.15 * speech_rate_steadiness +
                0.15 * (100.0 - p_spectral_entropy)
            )

        # === WELLBEING (personalized, HNR replaces jitter) ===
        wellbeing = (
            0.35 * (100.0 - p_dep) +
            0.25 * (100.0 - p_anx) +
            0.15 * (100.0 - p_shimmer) +
            0.15 * p_speech_rate +
            0.10 * p_hnr                       # HNR: clearer voice = better wellbeing
        )

        # === ACTIVATION (personalized, with spectral flux + sentiment arousal) ===
        if has_linguistic:
            activation = (
                0.25 * p_rms +
                0.22 * p_f0_std +
                0.18 * p_speech_rate +
                0.13 * p_spectral_centroid +
                0.08 * (100.0 - p_spectral_entropy) +
                0.08 * p_spectral_flux +
                0.06 * p_sentiment_arousal
            )
        else:
            activation = (
                0.27 * p_rms +
                0.23 * p_f0_std +
                0.20 * p_speech_rate +
                0.15 * p_spectral_centroid +
                0.08 * (100.0 - p_spectral_entropy) +
                0.07 * p_spectral_flux
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
                       uncertainty_flag: Optional[str] = None,
                       calm_score: float = 50.0) -> str:
        """
        Classify current state using convergence logic (AND gates).

        v2 audit change: Requires BOTH DAM and stress_score to agree before
        classifying as "stressed." A single noisy signal cannot force the
        most severe zone. Fallback: escalated OR-only signals → "tense."

        GAD-7 thresholds: 0-4 minimal, 5-9 mild, 10-14 moderate, 15-21 severe

        When uncertainty_flag is 'borderline', prefer the less severe zone.

        Calm uses calm_score (multi-feature composite) rather than dual AND logic,
        which was too strict and ignored the dedicated calm signal.
        """
        if uncertainty_flag == 'borderline':
            # Borderline: even stricter convergence required
            if anxiety_mapped >= 12 and stress_score > 65:
                return 'stressed'
            elif anxiety_mapped >= 12 or stress_score > 75:
                return 'tense'  # Escalated single-signal → tense (not stressed)
            elif anxiety_mapped >= 7 and stress_score > 45:
                return 'tense'
            elif anxiety_mapped >= 7 or stress_score > 55:
                return 'steady'  # Escalated single-signal → steady (not tense)
            elif calm_score >= 57 and stress_score < 45:
                return 'calm'
            else:
                return 'steady'
        else:
            # Normal: AND logic for stressed, OR falls through to tense
            if anxiety_mapped >= 10 and stress_score > 60:
                return 'stressed'
            elif anxiety_mapped >= 10 or stress_score > 70:
                return 'tense'  # Single signal elevated → tense (not stressed)
            elif anxiety_mapped >= 5 and stress_score > 35:
                return 'tense'
            elif calm_score >= 52 and stress_score < 45:
                return 'calm'
            else:
                return 'steady'

    def _compute_zone_confidence(self, dam_output: Dict, af: Dict,
                                  stress_score: float) -> str:
        """Compute confidence level for the zone classification.

        Returns 'high', 'moderate', or 'low' based on:
        - DAM uncertainty flag (borderline = lower confidence)
        - Agreement between DAM anxiety and acoustic stress score
        - Feature variance / quality indicators
        """
        confidence_score = 100.0

        # Penalty for borderline DAM reading
        if dam_output.get('uncertainty_flag') == 'borderline':
            confidence_score -= 30.0

        # Penalty for score inconsistency
        if dam_output.get('score_inconsistency', 0):
            confidence_score -= 15.0

        # Penalty for DAM-acoustic disagreement
        anx_mapped = dam_output.get('anxiety_mapped', 0.0)
        anx_zone_signal = 'calm' if anx_mapped < 3 else ('stressed' if anx_mapped >= 10 else 'moderate')
        stress_zone_signal = 'calm' if stress_score < 30 else ('stressed' if stress_score > 70 else 'moderate')
        if anx_zone_signal != stress_zone_signal:
            confidence_score -= 20.0

        # Penalty for very low speech quality indicators
        if af.get('f0_mean', 0.0) < 50:  # Implausibly low pitch = bad extraction
            confidence_score -= 15.0
        if af.get('hnr', 0.0) < 5:  # Very noisy audio
            confidence_score -= 10.0

        # Classify
        if confidence_score >= 70:
            return 'high'
        elif confidence_score >= 40:
            return 'moderate'
        else:
            return 'low'
