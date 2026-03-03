"""
Acoustic feature extraction using librosa
Extracts F0, pitch variability, RMS energy, speech rate, spectral features,
shimmer, and voice breaks.
"""
import logging
import numpy as np
import librosa
from typing import Dict

logger = logging.getLogger('lucid.acoustic')

class AcousticFeatureExtractor:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def _extract_pitch(self, audio: np.ndarray):
        """Extract pitch using pyin (called once, shared across features).

        Returns:
            Tuple of (f0, voiced_flag, voiced_probs) from librosa.pyin,
            or (None, None, None) on error.
        """
        try:
            f0, voiced_flag, voiced_probs = librosa.pyin(
                audio,
                fmin=librosa.note_to_hz('C2'),  # ~65 Hz
                fmax=librosa.note_to_hz('C7'),  # ~2093 Hz
                sr=self.sample_rate
            )
            return f0, voiced_flag, voiced_probs
        except Exception as e:
            logger.error(f"Error in pyin extraction: {e}")
            return None, None, None

    def extract(self, audio: np.ndarray) -> Dict[str, float]:
        """
        Extract all acoustic features from audio

        Args:
            audio: numpy array of audio samples

        Returns:
            Dict with acoustic features
        """
        features = {}

        try:
            # Ensure audio is float and non-empty
            audio = audio.astype(np.float32)
            if len(audio) == 0:
                return self._get_zero_features()

            # Run pyin once and share results across F0, jitter, shimmer, voice_breaks
            f0, voiced_flag, voiced_probs = self._extract_pitch(audio)

            # F0 (fundamental frequency) - pitch
            f0_mean, f0_std = self._extract_f0(audio, f0=f0)
            features['f0_mean'] = f0_mean
            features['f0_std'] = f0_std

            # RMS energy
            features['rms_energy'] = self._extract_rms(audio)

            # Speech rate (syllable-like energy peaks per second)
            features['speech_rate'] = self._extract_speech_rate(audio)

            # Spectral centroid (brightness of sound)
            features['spectral_centroid'] = self._extract_spectral_centroid(audio)

            # Spectral entropy (randomness of spectrum)
            features['spectral_entropy'] = self._extract_spectral_entropy(audio)

            # Zero crossing rate (correlates with vocal tension)
            features['zcr'] = self._extract_zcr(audio)

            # Jitter (pitch period variation)
            features['jitter'] = self._extract_jitter(audio, f0=f0)

            # Shimmer (amplitude variation across pitch periods)
            features['shimmer'] = self._extract_shimmer(audio, f0=f0)

            # Voice breaks (unvoiced gaps within speech)
            features['voice_breaks'] = self._extract_voice_breaks(audio, f0=f0)

            # Alpha ratio (energy ratio 0-1kHz vs 1-5kHz) — most reliable stress marker (Menne et al. 2025)
            features['alpha_ratio'] = self._extract_alpha_ratio(audio)

            # MFCC3 (3rd mel-frequency cepstral coefficient) — cortisol association (beta=-0.606, p=0.014)
            features['mfcc3'] = self._extract_mfcc3(audio)

            # HNR (harmonic-to-noise ratio) — voice quality, decreases under stress
            features['hnr'] = self._extract_hnr(audio, f0=f0)

            # F1/F2 formants via LPC — vowel space, vocal tract tension
            f1, f2 = self._extract_formants(audio)
            features['f1_mean'] = f1
            features['f2_mean'] = f2

            # Spectral flux — frame-to-frame spectral change, arousal/dynamism
            features['spectral_flux'] = self._extract_spectral_flux(audio)

            # Log results
            duration = len(audio) / self.sample_rate
            logger.info(f"Extracted features from {duration:.1f}s: "
                        f"F0={f0_mean:.1f}\u00b1{f0_std:.1f}Hz, "
                        f"Energy={features['rms_energy']:.3f}, "
                        f"Rate={features['speech_rate']:.1f}syl/s, "
                        f"Shimmer={features['shimmer']:.3f}, "
                        f"VoiceBreaks={features['voice_breaks']}")

            return features

        except Exception as e:
            logger.error(f"Error extracting features: {e}")
            return self._get_zero_features()

    def _extract_f0(self, audio: np.ndarray, f0=None) -> tuple:
        """Extract F0 mean and standard deviation.

        Args:
            audio: audio samples (used as fallback if f0 is None)
            f0: pre-computed F0 array from _extract_pitch() (optional)
        """
        try:
            if f0 is None:
                f0, _, _ = self._extract_pitch(audio)
                if f0 is None:
                    return 0.0, 0.0

            # Remove NaN values (unvoiced frames)
            f0_voiced = f0[~np.isnan(f0)]

            if len(f0_voiced) > 0:
                return float(np.mean(f0_voiced)), float(np.std(f0_voiced))
            else:
                return 0.0, 0.0

        except Exception as e:
            logger.error(f"Error in F0 extraction: {e}")
            return 0.0, 0.0

    def _extract_rms(self, audio: np.ndarray) -> float:
        """Extract RMS energy"""
        try:
            rms = librosa.feature.rms(y=audio)[0]
            return float(np.mean(rms))
        except Exception as e:
            logger.error(f"Error in RMS extraction: {e}")
            return 0.0

    def _extract_speech_rate(self, audio: np.ndarray) -> float:
        """
        Estimate speech rate by counting syllable-like energy peaks
        """
        try:
            # Use onset strength as proxy for syllable nuclei
            onset_env = librosa.onset.onset_strength(y=audio, sr=self.sample_rate)

            # Detect peaks (potential syllables)
            peaks = librosa.util.peak_pick(
                onset_env,
                pre_max=3,
                post_max=3,
                pre_avg=3,
                post_avg=5,
                delta=0.5,
                wait=10
            )

            # Calculate rate per second
            duration_sec = len(audio) / self.sample_rate
            rate = len(peaks) / duration_sec if duration_sec > 0 else 0.0

            return float(rate)

        except Exception as e:
            logger.error(f"Error in speech rate extraction: {e}")
            return 0.0

    def _extract_spectral_centroid(self, audio: np.ndarray) -> float:
        """Extract spectral centroid (brightness)"""
        try:
            centroid = librosa.feature.spectral_centroid(y=audio, sr=self.sample_rate)[0]
            return float(np.mean(centroid))
        except Exception as e:
            logger.error(f"Error in spectral centroid extraction: {e}")
            return 0.0

    def _extract_spectral_entropy(self, audio: np.ndarray) -> float:
        """Extract spectral entropy"""
        try:
            # Compute power spectrum
            S = np.abs(librosa.stft(audio))

            # Normalize to get probability distribution
            S_norm = S / (np.sum(S, axis=0, keepdims=True) + 1e-10)

            # Compute entropy for each frame
            entropy = -np.sum(S_norm * np.log(S_norm + 1e-10), axis=0)

            return float(np.mean(entropy))

        except Exception as e:
            logger.error(f"Error in spectral entropy extraction: {e}")
            return 0.0

    def _extract_zcr(self, audio: np.ndarray) -> float:
        """Extract zero crossing rate"""
        try:
            zcr = librosa.feature.zero_crossing_rate(audio)[0]
            return float(np.mean(zcr))
        except Exception as e:
            logger.error(f"Error in ZCR extraction: {e}")
            return 0.0

    def _extract_jitter(self, audio: np.ndarray, f0=None) -> float:
        """
        Extract jitter (pitch period variation)
        Simplified calculation based on F0 variations

        Args:
            audio: audio samples (used as fallback if f0 is None)
            f0: pre-computed F0 array from _extract_pitch() (optional)
        """
        try:
            if f0 is None:
                f0, _, _ = self._extract_pitch(audio)
                if f0 is None:
                    return 0.0

            # Remove NaN values
            f0_voiced = f0[~np.isnan(f0)]

            if len(f0_voiced) > 1:
                # Calculate relative variation between consecutive periods
                periods = 1.0 / (f0_voiced + 1e-10)
                period_diff = np.abs(np.diff(periods))
                jitter = np.mean(period_diff) / np.mean(periods) if np.mean(periods) > 0 else 0.0
                return float(jitter)
            else:
                return 0.0

        except Exception as e:
            logger.error(f"Error in jitter extraction: {e}")
            return 0.0

    def _extract_shimmer(self, audio: np.ndarray, f0=None) -> float:
        """
        Extract shimmer (amplitude variation across pitch periods).

        Shimmer = mean |A(i+1) - A(i)| / mean(A)
        where A(i) is the peak amplitude in pitch period i.

        Well-validated biomarker for depression (Cummins et al. 2015).

        Args:
            audio: audio samples (used as fallback if f0 is None)
            f0: pre-computed F0 array from _extract_pitch() (optional)
        """
        try:
            if f0 is None:
                f0, _, _ = self._extract_pitch(audio)
                if f0 is None:
                    return 0.0

            f0_voiced = f0[~np.isnan(f0)]
            if len(f0_voiced) < 2:
                return 0.0

            # Get pitch period boundaries using F0 estimates
            # librosa.pyin returns F0 per frame; we need per-period amplitudes
            hop_length = 512  # librosa default
            frame_times = librosa.frames_to_time(
                np.arange(len(f0)), sr=self.sample_rate, hop_length=hop_length
            )

            # For each voiced frame, get peak amplitude in the local period
            peak_amplitudes = []
            for i, (freq, is_voiced) in enumerate(zip(f0, ~np.isnan(f0))):
                if not is_voiced or freq < 50:
                    continue
                period_samples = int(self.sample_rate / freq)
                center = int(frame_times[i] * self.sample_rate)
                start = max(0, center - period_samples // 2)
                end = min(len(audio), center + period_samples // 2)
                if end > start:
                    peak_amplitudes.append(float(np.max(np.abs(audio[start:end]))))

            if len(peak_amplitudes) < 2:
                return 0.0

            amps = np.array(peak_amplitudes)
            mean_amp = np.mean(amps)
            if mean_amp < 1e-10:
                return 0.0

            # Shimmer: mean absolute difference / mean amplitude
            shimmer = float(np.mean(np.abs(np.diff(amps))) / mean_amp)
            return shimmer

        except Exception as e:
            logger.error(f"Error in shimmer extraction: {e}")
            return 0.0

    def _extract_voice_breaks(self, audio: np.ndarray, f0=None) -> int:
        """
        Count unvoiced gaps >200ms within speech.

        Strong signal for severe depression (Scherer et al. 2013).

        Args:
            audio: audio samples (used as fallback if f0 is None)
            f0: pre-computed F0 array from _extract_pitch() (optional)
        """
        try:
            if f0 is None:
                f0, _, _ = self._extract_pitch(audio)
                if f0 is None:
                    return 0

            # Find unvoiced (NaN) segments
            is_voiced = ~np.isnan(f0)
            hop_length = 512
            frame_duration = hop_length / self.sample_rate  # ~0.032s per frame
            min_gap_frames = int(0.2 / frame_duration)  # 200ms in frames (~6 frames)

            # Count consecutive unvoiced segments longer than min_gap_frames
            breaks = 0
            unvoiced_run = 0
            in_speech = False

            for voiced in is_voiced:
                if voiced:
                    if unvoiced_run >= min_gap_frames and in_speech:
                        breaks += 1
                    unvoiced_run = 0
                    in_speech = True
                else:
                    if in_speech:
                        unvoiced_run += 1

            return breaks

        except Exception as e:
            logger.error(f"Error in voice breaks extraction: {e}")
            return 0

    def _extract_alpha_ratio(self, audio: np.ndarray) -> float:
        """Extract alpha ratio: energy ratio of 0-1kHz vs 1-5kHz.

        Most reliable speech stress marker per Menne et al. 2025.
        Higher alpha ratio (more low-frequency energy) indicates relaxed phonation;
        lower ratio (more high-frequency energy) indicates tense phonation.
        """
        try:
            S = np.abs(librosa.stft(audio, n_fft=2048, hop_length=512)) ** 2
            freqs = librosa.fft_frequencies(sr=self.sample_rate, n_fft=2048)

            # Low band: 0-1000 Hz
            low_mask = freqs <= 1000
            # High band: 1000-5000 Hz
            high_mask = (freqs > 1000) & (freqs <= 5000)

            low_energy = np.sum(S[low_mask, :])
            high_energy = np.sum(S[high_mask, :])

            if high_energy < 1e-10:
                return 0.0

            # Alpha ratio in dB
            ratio = 10.0 * np.log10(low_energy / high_energy + 1e-10)
            return float(ratio)

        except Exception as e:
            logger.error(f"Error in alpha ratio extraction: {e}")
            return 0.0

    def _extract_mfcc3(self, audio: np.ndarray) -> float:
        """Extract 3rd MFCC coefficient (spectral envelope shape).

        Significant cortisol association (beta=-0.606, p=0.014).
        Lower MFCC3 associated with higher cortisol (stress).
        """
        try:
            mfccs = librosa.feature.mfcc(y=audio, sr=self.sample_rate, n_mfcc=4)
            # Index 2 = 3rd coefficient (0-indexed), averaged across frames
            return float(np.mean(mfccs[2, :]))

        except Exception as e:
            logger.error(f"Error in MFCC3 extraction: {e}")
            return 0.0

    def _extract_hnr(self, audio: np.ndarray, f0=None) -> float:
        """Extract Harmonic-to-Noise Ratio via autocorrelation method.

        Better validated than jitter for voice quality assessment.
        Higher HNR = clearer voice (less noise) = more relaxed.
        Lower HNR = breathier/noisier voice = more tension/stress.
        """
        try:
            if f0 is None:
                f0, _, _ = self._extract_pitch(audio)
                if f0 is None:
                    return 0.0

            f0_voiced = f0[~np.isnan(f0)]
            if len(f0_voiced) < 2:
                return 0.0

            median_f0 = np.median(f0_voiced)
            if median_f0 < 50:
                return 0.0

            # Compute autocorrelation at the pitch period
            period_samples = int(self.sample_rate / median_f0)
            if period_samples < 2 or period_samples >= len(audio):
                return 0.0

            # Frame-based HNR estimation
            frame_length = period_samples * 4  # 4 pitch periods per frame
            hop = frame_length // 2
            hnr_values = []

            for start in range(0, len(audio) - frame_length, hop):
                frame = audio[start:start + frame_length].astype(np.float64)
                # Autocorrelation
                ac = np.correlate(frame, frame, mode='full')
                ac = ac[len(ac) // 2:]  # Take positive lags
                ac_norm = ac / (ac[0] + 1e-10)  # Normalize

                if period_samples < len(ac_norm):
                    # Peak at pitch period lag
                    r_t0 = ac_norm[period_samples]
                    if r_t0 > 0 and r_t0 < 1.0:
                        hnr_db = 10.0 * np.log10(r_t0 / (1.0 - r_t0 + 1e-10))
                        hnr_values.append(hnr_db)

            if len(hnr_values) == 0:
                return 0.0

            return float(np.median(hnr_values))

        except Exception as e:
            logger.error(f"Error in HNR extraction: {e}")
            return 0.0

    def _extract_formants(self, audio: np.ndarray) -> tuple:
        """Estimate F1/F2 formant frequencies via LPC analysis.

        Uses librosa.lpc to compute linear predictive coding coefficients,
        then finds polynomial roots to extract formant frequencies.
        F1 and F2 correspond to the first two resonant frequencies of the vocal tract.
        F1 correlates with tongue height; F2 with tongue backness.
        Elevated F1 under stress (Protopapas & Lieberman 1997).

        Returns:
            Tuple of (f1_mean, f2_mean) in Hz, or (0.0, 0.0) on error.
        """
        try:
            if len(audio) < self.sample_rate * 0.1:  # Need at least 100ms
                return 0.0, 0.0

            # Use 25ms frames with 10ms hop for formant analysis
            frame_len = int(0.025 * self.sample_rate)  # 400 samples at 16kHz
            hop_len = int(0.010 * self.sample_rate)     # 160 samples

            # LPC order: 2 + sample_rate/1000 (standard heuristic)
            lpc_order = 2 + int(self.sample_rate / 1000)  # 18 for 16kHz

            f1_vals = []
            f2_vals = []

            for start in range(0, len(audio) - frame_len, hop_len):
                frame = audio[start:start + frame_len].astype(np.float64)

                # Apply Hanning window
                frame = frame * np.hanning(len(frame))

                # Skip low-energy frames (silence/noise)
                if np.std(frame) < 1e-5:
                    continue

                try:
                    # Compute LPC coefficients
                    lpc_coeffs = librosa.lpc(frame, order=lpc_order)

                    # Find roots of LPC polynomial
                    roots = np.roots(lpc_coeffs)

                    # Keep roots inside unit circle (stable) with positive imaginary part
                    roots = roots[np.abs(roots) < 1.0]
                    roots = roots[np.imag(roots) > 0]

                    if len(roots) < 2:
                        continue

                    # Convert roots to frequencies
                    angles = np.angle(roots)
                    freqs = angles * (self.sample_rate / (2 * np.pi))
                    freqs = np.sort(freqs)

                    # Filter to speech formant range (200-3500 Hz)
                    speech_freqs = freqs[(freqs >= 200) & (freqs <= 3500)]

                    if len(speech_freqs) >= 2:
                        f1_vals.append(speech_freqs[0])
                        f2_vals.append(speech_freqs[1])
                    elif len(speech_freqs) == 1:
                        f1_vals.append(speech_freqs[0])

                except Exception:
                    continue

            f1 = float(np.median(f1_vals)) if f1_vals else 0.0
            f2 = float(np.median(f2_vals)) if f2_vals else 0.0

            return f1, f2

        except Exception as e:
            logger.error(f"Error in formant extraction: {e}")
            return 0.0, 0.0

    def _extract_spectral_flux(self, audio: np.ndarray) -> float:
        """Compute spectral flux: mean frame-to-frame spectral change.

        Spectral flux measures how quickly the power spectrum changes over time.
        High flux = more dynamic/expressive speech (arousal).
        Low flux = more monotone/flat delivery.

        Uses L2 norm of magnitude spectrum difference between consecutive frames.
        """
        try:
            if len(audio) < 512:
                return 0.0

            # Compute magnitude spectrogram
            S = np.abs(librosa.stft(audio, n_fft=2048, hop_length=512))

            if S.shape[1] < 2:
                return 0.0

            # Normalize each frame to unit sum (focus on shape change, not energy)
            S_norm = S / (np.sum(S, axis=0, keepdims=True) + 1e-10)

            # Compute frame-to-frame L2 difference
            diff = np.diff(S_norm, axis=1)
            flux_per_frame = np.sqrt(np.sum(diff ** 2, axis=0))

            return float(np.mean(flux_per_frame))

        except Exception as e:
            logger.error(f"Error in spectral flux extraction: {e}")
            return 0.0

    def _get_zero_features(self) -> Dict[str, float]:
        """Return dict of zero features (for error cases)"""
        return {
            'f0_mean': 0.0,
            'f0_std': 0.0,
            'rms_energy': 0.0,
            'speech_rate': 0.0,
            'spectral_centroid': 0.0,
            'spectral_entropy': 0.0,
            'zcr': 0.0,
            'jitter': 0.0,
            'shimmer': 0.0,
            'voice_breaks': 0,
            'alpha_ratio': 0.0,
            'mfcc3': 0.0,
            'hnr': 0.0,
            'f1_mean': 0.0,
            'f2_mean': 0.0,
            'spectral_flux': 0.0,
        }
