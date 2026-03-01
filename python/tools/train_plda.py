#!/usr/bin/env python3
"""
Offline PLDA training script for Attune speaker verification.

Trains a PLDA model from pre-extracted ECAPA-TDNN embeddings.
The trained model improves speaker discrimination beyond cosine similarity.

Usage:
    # 1. Extract embeddings from VoxCeleb (or similar) using ECAPA-TDNN
    #    Save as: embeddings.npy (N x 192), labels.npy (N,) with speaker IDs

    # 2. Train PLDA
    python tools/train_plda.py --embeddings embeddings.npy --labels labels.npy --output data/plda_model.pkl

    # 3. Enable in app_config.py
    #    PLDA_ENABLED = True

Requirements:
    - numpy
    - speechbrain (for PLDA_LDA)
    - Pre-extracted speaker embeddings with labels
"""
import argparse
import pickle
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('train_plda')


def train_plda(embeddings: np.ndarray, labels: np.ndarray, output_path: str):
    """Train PLDA model from embeddings and speaker labels.

    Args:
        embeddings: (N, 192) array of ECAPA-TDNN embeddings
        labels: (N,) array of speaker ID strings/ints
        output_path: where to save the trained model pickle
    """
    from speechbrain.processing.PLDA_LDA import PLDA, StatObject_SB

    logger.info(f"Training PLDA on {len(embeddings)} embeddings from {len(set(labels))} speakers")

    # Center embeddings
    mean = np.mean(embeddings, axis=0)
    centered = embeddings - mean

    # Create StatObject
    unique_labels = sorted(set(labels))
    label_to_idx = {l: str(i) for i, l in enumerate(unique_labels)}

    stat = StatObject_SB()
    stat.modelset = np.array([label_to_idx[l] for l in labels])
    stat.segset = np.array([f'seg_{i}' for i in range(len(labels))])
    stat.stat0 = np.ones((len(labels), 1))
    stat.stat1 = centered.astype(np.float64)

    # Train PLDA
    plda = PLDA()
    plda.plda(stat)

    # Save
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'wb') as f:
        pickle.dump({'plda': plda, 'mean': mean}, f)

    logger.info(f"PLDA model saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Train PLDA model for speaker verification')
    parser.add_argument('--embeddings', required=True, help='Path to embeddings .npy file (N x 192)')
    parser.add_argument('--labels', required=True, help='Path to labels .npy file (N,)')
    parser.add_argument('--output', default='data/plda_model.pkl', help='Output model path')
    args = parser.parse_args()

    embeddings = np.load(args.embeddings)
    labels = np.load(args.labels, allow_pickle=True)

    logger.info(f"Loaded {embeddings.shape[0]} embeddings ({embeddings.shape[1]}-dim)")
    logger.info(f"Speakers: {len(set(labels))}")

    train_plda(embeddings, labels, args.output)


if __name__ == '__main__':
    main()
