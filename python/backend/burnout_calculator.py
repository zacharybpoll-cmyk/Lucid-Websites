"""
Burnout risk calculator
Computes 14-day rolling burnout risk and resilience scores
"""
from typing import Dict, List, Any
from datetime import date, timedelta


class BurnoutCalculator:
    def __init__(self, db):
        self.db = db

    def compute_burnout_risk(self, days: int = 14) -> Dict[str, Any]:
        """
        Compute burnout risk from last N days of data

        Returns:
            {
                'burnout_risk': float (0-100),
                'resilience_score': float (0-100),
                'trend_direction': str ('improving'|'stable'|'declining'),
                'contributors': dict with component scores
            }
        """
        summaries = self.db.get_daily_summaries(days=days)

        if not summaries or len(summaries) < 1:
            return {
                'burnout_risk': 0,
                'resilience_score': 100,
                'trend_direction': 'stable',
                'contributors': {
                    'avg_stress_trend': 0,
                    'inverse_mood_trend': 0,
                    'peak_stress_frequency': 0,
                    'low_calm_ratio': 0
                }
            }

        # Component 1: Average stress trend (already 0-100)
        stress_values = [s.get('avg_stress', 0) for s in summaries if s.get('avg_stress') is not None]
        avg_stress_trend = sum(stress_values) / len(stress_values) if stress_values else 0

        # Component 2: Inverse mood trend
        mood_values = [s.get('avg_mood', 50) for s in summaries if s.get('avg_mood') is not None]
        avg_mood = sum(mood_values) / len(mood_values) if mood_values else 50
        inverse_mood_trend = 100 - avg_mood

        # Component 3: Peak stress frequency (% of days with peak > 70)
        peak_stress_days = sum(1 for s in summaries if s.get('peak_stress', 0) > 70)
        peak_stress_frequency = (peak_stress_days / len(summaries)) * 100

        # Component 4: Low calm ratio (% of days with < 15 min calm)
        low_calm_days = sum(1 for s in summaries if s.get('time_in_calm_min', 0) < 15)
        low_calm_ratio = (low_calm_days / len(summaries)) * 100

        # Weighted composite
        burnout_risk = (
            0.4 * avg_stress_trend +
            0.3 * inverse_mood_trend +
            0.2 * peak_stress_frequency +
            0.1 * low_calm_ratio
        )

        # Clamp to 0-100
        burnout_risk = max(0, min(100, burnout_risk))

        # Resilience = inverse of burnout
        resilience_score = 100 - burnout_risk

        # Trend direction: compare last 3 days vs previous 3 days
        trend_direction = self._compute_trend_direction(summaries)

        return {
            'burnout_risk': round(burnout_risk, 1),
            'resilience_score': round(resilience_score, 1),
            'trend_direction': trend_direction,
            'contributors': {
                'avg_stress_trend': round(avg_stress_trend, 1),
                'inverse_mood_trend': round(inverse_mood_trend, 1),
                'peak_stress_frequency': round(peak_stress_frequency, 1),
                'low_calm_ratio': round(low_calm_ratio, 1)
            }
        }

    def _compute_trend_direction(self, summaries: List[Dict]) -> str:
        """Compare stress in last 3 days vs previous 3 days"""
        if len(summaries) < 6:
            return 'stable'

        # Sort by date (most recent first from DB)
        summaries = sorted(summaries, key=lambda s: s['date'], reverse=True)

        # Last 3 days (most recent)
        recent = summaries[:3]
        recent_stress = [s.get('avg_stress', 50) for s in recent if s.get('avg_stress') is not None]
        recent_avg = sum(recent_stress) / len(recent_stress) if recent_stress else 50

        # Previous 3 days
        previous = summaries[3:6]
        prev_stress = [s.get('avg_stress', 50) for s in previous if s.get('avg_stress') is not None]
        prev_avg = sum(prev_stress) / len(prev_stress) if prev_stress else 50

        # Compare
        diff = recent_avg - prev_avg

        if diff < -5:
            return 'improving'
        elif diff > 5:
            return 'declining'
        else:
            return 'stable'
