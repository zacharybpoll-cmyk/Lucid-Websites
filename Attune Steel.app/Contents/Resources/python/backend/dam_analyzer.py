"""
DAM (Depression-Anxiety Model) analyzer
Wraps KintsugiHealth DAM model for inference.

Includes:
- Confidence intervals on mapped PHQ-9/GAD-7 scores
- Indeterminate zone detection for borderline readings
- Quantized-output consistency checking
"""
import logging
import sys
import traceback
import hashlib
import numpy as np
import soundfile as sf
import torch
import tempfile
from pathlib import Path
from typing import Dict, Optional
import app_config as config

logger = logging.getLogger('attune.dam')

DAM_PATH = config.DAM_DIR
DAM_HASH_FILE = Path(config.DATA_DIR) / '.dam_model_hash'

# Import score mapper (lives in dam/ directory)
sys.path.insert(0, str(DAM_PATH))
from score_mapper import (
    map_depression, map_anxiety,
    map_depression_with_ci, map_anxiety_with_ci,
    get_global_residual_std,
)
sys.path.pop(0)

# Indeterminate zone bands (Step 7)
# When raw score is within ±0.15 of a quantization threshold, mark as borderline
# Depression thresholds from DAM: [-0.6699, -0.2908]
DEPRESSION_UNCERTAIN_BANDS = [(-0.82, -0.52), (-0.44, -0.14)]
# Anxiety thresholds from DAM: [-0.7903, -0.2209, 0.1503]
ANXIETY_UNCERTAIN_BANDS = [(-0.94, -0.64), (-0.37, -0.07), (0.00, 0.30)]

# Quantized-to-clinical-range mapping (Step 8)
QUANT_TO_PHQ_RANGE = {0: (0, 9), 1: (10, 14), 2: (15, 27)}
QUANT_TO_GAD_RANGE = {0: (0, 4), 1: (5, 9), 2: (10, 14), 3: (15, 21)}


def _in_uncertain_band(raw: float, bands: list) -> bool:
    """Check if raw score falls within any uncertain band."""
    return any(lo <= raw <= hi for lo, hi in bands)


def _check_consistency(mapped: float, quantized: int, range_map: dict) -> bool:
    """Check if mapped score is consistent with quantized level."""
    if quantized not in range_map:
        return True  # Unknown level, assume consistent
    lo, hi = range_map[quantized]
    return lo <= mapped <= hi


def _compute_dam_checksum() -> str:
    """Compute SHA-256 over all model files in DAM_PATH (sorted for determinism)."""
    h = hashlib.sha256()
    model_files = sorted(Path(DAM_PATH).rglob('*.bin')) + sorted(Path(DAM_PATH).rglob('*.pt'))
    for fp in model_files:
        h.update(fp.read_bytes())
    return h.hexdigest()


def _verify_dam_integrity():
    """Verify DAM model files haven't changed. Save hash on first run, warn on mismatch."""
    try:
        current_hash = _compute_dam_checksum()
        if DAM_HASH_FILE.exists():
            saved_hash = DAM_HASH_FILE.read_text().strip()
            if saved_hash != current_hash:
                logger.warning(f"Model checksum mismatch! "
                               f"Expected {saved_hash[:16]}..., got {current_hash[:16]}... "
                               f"Model files may have been modified or corrupted.")
            else:
                logger.info("Model integrity verified (SHA-256 match)")
        else:
            DAM_HASH_FILE.write_text(current_hash)
            logger.info(f"Model hash saved for future verification: {current_hash[:16]}...")
    except Exception as e:
        logger.warning(f"Could not verify model integrity: {e}")


class DAMAnalyzer:
    def __init__(self):
        self.pipeline = None
        self._load_model()

    def _load_model(self):
        """Load DAM pipeline with sys.path isolation"""
        try:
            logger.info("Loading DAM model...")
            # Temporarily add DAM to sys.path, import, then restore
            saved_path = sys.path[:]
            sys.path.insert(0, str(DAM_PATH))
            try:
                # Patch torchaudio.load to use soundfile directly.
                # torchaudio 2.10 removed the old backend system and requires
                # TorchCodec, which is not installed. We bypass it entirely.
                import torchaudio
                def _soundfile_load(source, frame_offset=0, num_frames=-1,
                                    normalize=True, channels_first=True,
                                    format=None, buffer_size=4096, backend=None):
                    data, sample_rate = sf.read(source, dtype='float32',
                                                start=frame_offset,
                                                stop=frame_offset + num_frames if num_frames > 0 else None)
                    audio_tensor = torch.from_numpy(data)
                    if audio_tensor.ndim == 1:
                        audio_tensor = audio_tensor.unsqueeze(0)  # (1, samples)
                    elif channels_first:
                        audio_tensor = audio_tensor.T  # (channels, samples)
                    return audio_tensor, sample_rate
                torchaudio.load = _soundfile_load
                from pipeline import Pipeline
                self.pipeline = Pipeline()
            finally:
                sys.path[:] = saved_path
            _verify_dam_integrity()
            logger.info("DAM model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading DAM model: {e}")
            logger.error(f"Make sure the DAM repository is cloned at: {DAM_PATH}")
            raise

    def analyze(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[Dict[str, float]]:
        """
        Analyze audio and return depression/anxiety scores with CIs and flags.

        Args:
            audio: numpy array of audio samples (mono, float32)
            sample_rate: sample rate (must be 16000 for DAM)

        Returns:
            Dict with raw, mapped, quantized, CI, and quality flag scores.
        """
        if self.pipeline is None:
            raise RuntimeError("DAM pipeline not loaded")

        if sample_rate != 16000:
            raise ValueError("DAM model requires 16kHz sample rate")

        tmp_path = None
        try:
            # Create temporary WAV file for DAM input
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name

            # Write audio to temp file
            sf.write(tmp_path, audio, sample_rate, subtype='PCM_16')

            # Run DAM inference with raw (unquantized) scores
            result_raw = self.pipeline.run_on_file(tmp_path, quantize=False)

            # Extract raw scores
            dep_tensor = result_raw.get('depression', torch.tensor(0.0))
            anx_tensor = result_raw.get('anxiety', torch.tensor(0.0))
            dep_raw = dep_tensor.item() if hasattr(dep_tensor, 'item') else float(dep_tensor)
            anx_raw = anx_tensor.item() if hasattr(anx_tensor, 'item') else float(anx_tensor)

            # Get quantized scores
            try:
                result_quantized = self.pipeline.model.quantize_scores(result_raw)
                dep_q = int(result_quantized['depression'].item())
                anx_q = int(result_quantized['anxiety'].item())
            except (AttributeError, KeyError) as e:
                logger.debug("Tensor .item() failed, trying dict access: %s", e)
                result_quantized = self.pipeline.run_on_file(tmp_path, quantize=True)
                dep_q = int(result_quantized.get('depression', 0))
                anx_q = int(result_quantized.get('anxiety', 0))

            # Map raw floats to clinical scales with confidence intervals (Step 5)
            dep_mapped, dep_ci_lo, dep_ci_hi = map_depression_with_ci(dep_raw)
            anx_mapped, anx_ci_lo, anx_ci_hi = map_anxiety_with_ci(anx_raw)

            # Check indeterminate zones (Step 7)
            dep_borderline = _in_uncertain_band(dep_raw, DEPRESSION_UNCERTAIN_BANDS)
            anx_borderline = _in_uncertain_band(anx_raw, ANXIETY_UNCERTAIN_BANDS)
            uncertainty_flag = None
            if dep_borderline or anx_borderline:
                uncertainty_flag = 'borderline'

            # Check quantized-output consistency (Step 8)
            dep_consistent = _check_consistency(dep_mapped, dep_q, QUANT_TO_PHQ_RANGE)
            anx_consistent = _check_consistency(anx_mapped, anx_q, QUANT_TO_GAD_RANGE)
            score_inconsistency = not (dep_consistent and anx_consistent)

            # Widen CI by 50% when inconsistent
            if score_inconsistency:
                dep_width = dep_ci_hi - dep_ci_lo
                dep_ci_lo = float(np.clip(dep_mapped - dep_width * 0.75, 0, 27))
                dep_ci_hi = float(np.clip(dep_mapped + dep_width * 0.75, 0, 27))
                anx_width = anx_ci_hi - anx_ci_lo
                anx_ci_lo = float(np.clip(anx_mapped - anx_width * 0.75, 0, 21))
                anx_ci_hi = float(np.clip(anx_mapped + anx_width * 0.75, 0, 21))

            output = {
                'depression_raw': float(dep_raw),
                'anxiety_raw': float(anx_raw),
                'depression_mapped': float(dep_mapped),
                'anxiety_mapped': float(anx_mapped),
                'depression_quantized': dep_q,
                'anxiety_quantized': anx_q,
                'depression_ci_lower': dep_ci_lo,
                'depression_ci_upper': dep_ci_hi,
                'anxiety_ci_lower': anx_ci_lo,
                'anxiety_ci_upper': anx_ci_hi,
                'uncertainty_flag': uncertainty_flag,
                'score_inconsistency': 1 if score_inconsistency else 0,
            }

            duration = len(audio) / sample_rate
            flags = []
            if uncertainty_flag:
                flags.append(f"BORDERLINE(dep={dep_borderline},anx={anx_borderline})")
            if score_inconsistency:
                flags.append("INCONSISTENT")
            flag_str = f" [{', '.join(flags)}]" if flags else ""

            logger.info(f"Analyzed {duration:.1f}s - "
                        f"Depression: {dep_raw:.2f} -> PHQ-9 {dep_mapped:.1f} [{dep_ci_lo:.1f}-{dep_ci_hi:.1f}] (Q{dep_q}), "
                        f"Anxiety: {anx_raw:.2f} -> GAD-7 {anx_mapped:.1f} [{anx_ci_lo:.1f}-{anx_ci_hi:.1f}] (Q{anx_q})"
                        f"{flag_str}")

            return output

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            traceback.print_exc()
            return None

        finally:
            # Clean up temp file
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError:
                    pass  # Temp file cleanup is best-effort
