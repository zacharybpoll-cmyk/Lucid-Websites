"""
PLDA scoring backend for speaker verification.

Wraps SpeechBrain's PLDA implementation to compute log-likelihood ratios
between enrollment embeddings and test embeddings. Provides better
discrimination than cosine similarity when trained on sufficient data.

Disabled by default — requires a trained PLDA model (see tools/train_plda.py).
"""
import logging
import pickle
import numpy as np
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger('attune.plda')


class PLDAScorer:
    def __init__(self):
        self._plda = None
        self._embedding_mean = None
        self._loaded = False

    def load_model(self, path: str) -> bool:
        """Load a trained PLDA model from pickle file.

        The pickle should contain:
            - 'plda': trained PLDA object (speechbrain.processing.PLDA_LDA.PLDA)
            - 'mean': embedding mean vector used for centering

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            model_path = Path(path)
            if not model_path.exists():
                logger.info(f"PLDA model not found at {path}")
                return False

            with open(model_path, 'rb') as f:
                data = pickle.load(f)

            self._plda = data['plda']
            self._embedding_mean = data['mean']
            self._loaded = True
            logger.info(f"PLDA model loaded from {path}")
            return True

        except Exception as e:
            logger.warning(f"Failed to load PLDA model: {e}")
            self._loaded = False
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def score(self, enrollment_embeddings: List[np.ndarray],
              test_embedding: np.ndarray) -> Optional[float]:
        """Compute PLDA log-likelihood ratio score.

        Args:
            enrollment_embeddings: list of enrollment embedding vectors
            test_embedding: test embedding to verify

        Returns:
            Sigmoid-normalized score in [0, 1] range, or None on failure
        """
        if not self._loaded:
            return None

        try:
            from speechbrain.processing.PLDA_LDA import StatObject_SB, fast_PLDA_scoring

            # Center embeddings
            enroll_centered = [e - self._embedding_mean for e in enrollment_embeddings]
            test_centered = test_embedding - self._embedding_mean

            # Create StatObject for enrollment
            enroll_array = np.array(enroll_centered)
            enroll_stat = StatObject_SB()
            enroll_stat.modelset = np.array([f'spk_{i}' for i in range(len(enroll_centered))])
            enroll_stat.segset = enroll_stat.modelset.copy()
            enroll_stat.stat0 = np.ones((len(enroll_centered), 1))
            enroll_stat.stat1 = enroll_array

            # Create StatObject for test
            test_stat = StatObject_SB()
            test_stat.modelset = np.array(['test_0'])
            test_stat.segset = test_stat.modelset.copy()
            test_stat.stat0 = np.ones((1, 1))
            test_stat.stat1 = test_centered.reshape(1, -1)

            # Score
            scores = fast_PLDA_scoring(
                enroll_stat, test_stat, self._plda.mean,
                self._plda.F, self._plda.Sigma
            )

            # Take max LLR across enrollment models
            llr = float(np.max(scores.scoremat))

            # Sigmoid normalization: LLR → [0, 1]
            normalized = 1.0 / (1.0 + np.exp(-llr))
            return normalized

        except Exception as e:
            logger.warning(f"PLDA scoring failed: {e}")
            return None
