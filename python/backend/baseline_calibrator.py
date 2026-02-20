"""
Personal baseline calibrator
Computes running statistics for personalized scoring
"""
import logging
import numpy as np
from typing import Dict, List, Optional
from backend.database import Database
import app_config as config

logger = logging.getLogger('attune.calibration')

class BaselineCalibrator:
    def __init__(self, db: Database):
        self.db = db
        self.calibration_days = config.CALIBRATION_DAYS

    def is_calibrated(self) -> bool:
        """Check if calibration period is complete"""
        baselines = self.db.get_all_baselines()

        # Check if we have baselines for key metrics
        required_metrics = [
            'depression_raw', 'anxiety_raw', 'stress_score',
            'mood_score', 'energy_score', 'calm_score'
        ]

        for metric in required_metrics:
            if metric not in baselines:
                return False
            if baselines[metric]['samples'] < 10:  # Minimum 10 readings
                return False

        return True

    def update_baselines(self):
        """Update all baselines from recent readings"""
        # Get readings from calibration period
        readings = self.db.get_readings(limit=1000)

        if len(readings) < 10:
            logger.info("Not enough readings yet for calibration")
            return

        # Update baseline for each metric
        metrics = [
            'depression_raw', 'anxiety_raw',
            'depression_mapped', 'anxiety_mapped',
            'stress_score', 'mood_score', 'energy_score', 'calm_score',
            'f0_mean', 'f0_std', 'rms_energy', 'speech_rate',
            'jitter', 'spectral_centroid', 'spectral_entropy',
            'shimmer', 'voice_breaks', 'vad_confidence',
        ]

        for metric in metrics:
            values = [r[metric] for r in readings if r.get(metric) is not None]

            if len(values) >= 10:
                mean = float(np.mean(values))
                std = float(np.std(values))
                self.db.update_baseline(metric, mean, std, len(values))

        status = "complete" if self.is_calibrated() else "in progress"
        logger.info(f"Updated baselines from {len(readings)} readings - Status: {status}")

    def normalize_score(self, metric: str, value: float, target_range: tuple = (0, 100)) -> float:
        """
        Normalize a metric value to target range using personal baseline

        Args:
            metric: Name of the metric
            value: Raw metric value
            target_range: Desired output range (min, max)

        Returns:
            Normalized score
        """
        baseline = self.db.get_baseline(metric)

        if baseline is None:
            # No baseline yet, return middle of range
            return (target_range[0] + target_range[1]) / 2

        mean = baseline['mean']
        std = baseline['std']

        if std == 0:
            # No variance, return middle of range
            return (target_range[0] + target_range[1]) / 2

        # Calculate z-score
        z_score = (value - mean) / std

        # Clamp z-score to [-3, 3] (99.7% of data)
        z_score = np.clip(z_score, -3, 3)

        # Map to target range
        # z = -3 -> target_range[0]
        # z = 3 -> target_range[1]
        normalized = ((z_score + 3) / 6) * (target_range[1] - target_range[0]) + target_range[0]

        return float(normalized)

    def get_calibration_status(self) -> Dict:
        """Get calibration status for UI"""
        baselines = self.db.get_all_baselines()
        total_readings = len(self.db.get_readings(limit=1000))

        return {
            'is_calibrated': self.is_calibrated(),
            'total_readings': total_readings,
            'baselines_count': len(baselines),
            'calibration_days': self.calibration_days,
            'min_readings': 10
        }
