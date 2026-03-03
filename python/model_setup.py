"""
model_setup.py — Must be imported BEFORE any torch/HuggingFace imports.
Sets HF_HOME, TORCH_HOME, and LUCID_SPEAKER_CACHE_DIR env vars so that
all model loading goes to the app-controlled cache directory.

In dev mode (no LUCID_BUNDLED_MODELS_DIR env var), does nothing —
the default HF/torch caches are used as normal.
"""
import os
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_model_cache():
    """Copy bundled models to DATA_DIR on first launch and set env vars."""
    bundled_dir = os.environ.get('LUCID_BUNDLED_MODELS_DIR')
    if not bundled_dir:
        return  # Dev mode — use default HF/torch caches normally

    data_dir = Path(os.environ.get('LUCID_DATA_DIR', Path.home() / 'lucid-data'))
    cache_dir = data_dir / 'model_cache'
    hf_home = cache_dir / 'hf_home'
    torch_home = cache_dir / 'torch_home'
    speaker_cache = cache_dir / 'speaker_model'

    bundled = Path(bundled_dir)

    # Copy on first launch (check presence of a sentinel file)
    sentinel = cache_dir / '.models_ready'
    if not sentinel.exists():
        logger.info("First launch: copying bundled models to user data dir...")
        for src, dst in [
            (bundled / 'hf_home', hf_home),
            (bundled / 'torch_home', torch_home),
            (bundled / 'speaker_model', speaker_cache),
        ]:
            if src.exists() and not dst.exists():
                logger.info(f"  Copying {src.name}...")
                shutil.copytree(src, dst)
        cache_dir.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        logger.info("Model cache ready.")

    # Set env vars BEFORE any torch/HF imports in the rest of the app
    os.environ['HF_HOME'] = str(hf_home)
    os.environ['TORCH_HOME'] = str(torch_home)
    os.environ['LUCID_SPEAKER_CACHE_DIR'] = str(speaker_cache)
