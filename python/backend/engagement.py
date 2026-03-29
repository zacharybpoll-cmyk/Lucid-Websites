import logging
"""
Engagement tracker with milestones, rhythm rings, and voice season
"""
from typing import Dict, List, Any, Optional
from datetime import date, datetime, timedelta
import csv
import io
import json
import math


logger = logging.getLogger('lucid.engagement')


class EngagementTracker:
    def __init__(self, db):
        self.db = db

    # ============ Rhythm Rings (Feature #5) ============

    def compute_rhythm_rings(self) -> Dict[str, Any]:
        """Compute today's progress toward 3 daily rings."""
        today_readings = self.db.get_today_readings()
        summary = self.db.compute_daily_summary()

        # Get or create adaptive targets
        goals = self.db.get_current_goals()
        if not goals:
            # Create default goals
            today = date.today()
            week_start = (today - timedelta(days=today.weekday())).isoformat()
            self.db.set_goals(week_start, speak=15, calm=15, checkin=5)
            goals = {'speak_target': 15, 'calm_target': 15, 'checkin_target': 5}

        speak_target = goals['speak_target']
        calm_target = goals['calm_target']
        checkin_target = goals['checkin_target']

        # Compute current values
        speak_current = summary.get('total_speech_min', 0) if summary else 0
        calm_current = summary.get('time_in_calm_min', 0) if summary else 0
        checkin_current = len(today_readings)

        speak_pct = min(100, (speak_current / speak_target) * 100) if speak_target > 0 else 0
        calm_pct = min(100, (calm_current / calm_target) * 100) if calm_target > 0 else 0
        checkin_pct = min(100, (checkin_current / checkin_target) * 100) if checkin_target > 0 else 0

        all_closed = speak_pct >= 100 and calm_pct >= 100 and checkin_pct >= 100

        return {
            'speak': {'current': round(speak_current, 1), 'target': speak_target, 'pct': round(speak_pct)},
            'calm': {'current': round(calm_current, 1), 'target': calm_target, 'pct': round(calm_pct)},
            'checkin': {'current': checkin_current, 'target': checkin_target, 'pct': round(checkin_pct)},
            'all_closed': all_closed,
        }

    def adapt_goals(self):
        """Adapt next week's goals based on last week's actuals (+5% stretch)."""
        today = date.today()
        last_week_start = today - timedelta(days=today.weekday() + 7)
        last_week_end = last_week_start + timedelta(days=6)

        # Get last week's summaries
        summaries = self.db.get_daily_summaries(days=14)
        last_week = [s for s in summaries
                     if last_week_start.isoformat() <= s['date'] <= last_week_end.isoformat()]

        if not last_week:
            return

        avg_speak = sum(s.get('total_speech_min', 0) for s in last_week) / len(last_week)
        avg_calm = sum(s.get('time_in_calm_min', 0) for s in last_week) / len(last_week)

        # Count average readings per day (estimate from speech time)
        avg_checkins = max(5, round(avg_speak / 5))  # roughly 1 reading per 5 min speech

        # +5% stretch
        new_speak = max(10, round(avg_speak * 1.05, 1))
        new_calm = max(10, round(avg_calm * 1.05, 1))
        new_checkin = max(3, round(avg_checkins * 1.05))

        this_week_start = (today - timedelta(days=today.weekday())).isoformat()
        self.db.set_goals(this_week_start, new_speak, new_calm, new_checkin)

    # ============ Voice Season (90-Day Arc) ============

    def compute_voice_season(self) -> Dict[str, Any]:
        """Compute current voice season progress.

        Each season is 90 days. Phase breakdown:
        - Discovery: days 1-30
        - Patterns: days 31-60
        - Prediction: days 61-90
        """
        summaries = self.db.get_daily_summaries(days=365)
        if not summaries:
            return {
                'has_data': False,
                'season_number': 1,
                'day': 0,
                'phase': 'Discovery',
                'phase_day': 0,
                'progress_pct': 0,
                'total_readings': 0,
            }

        total_days = len(summaries)
        total_readings = self.db.count_readings()

        # Season number (1-indexed)
        season_number = (total_days - 1) // 90 + 1
        day_in_season = ((total_days - 1) % 90) + 1

        # Phase determination
        if day_in_season <= 30:
            phase = 'Discovery'
            phase_day = day_in_season
        elif day_in_season <= 60:
            phase = 'Patterns'
            phase_day = day_in_season - 30
        else:
            phase = 'Prediction'
            phase_day = day_in_season - 60

        progress_pct = round(day_in_season / 90 * 100)

        # Check for phase transitions (just crossed day 31 or 61)
        phase_transition = None
        if day_in_season == 31:
            phase_transition = {'new_phase': 'Patterns', 'day': 31}
        elif day_in_season == 61:
            phase_transition = {'new_phase': 'Prediction', 'day': 61}

        # Check for season complete
        season_complete = day_in_season == 90

        return {
            'has_data': True,
            'season_number': season_number,
            'day': day_in_season,
            'total_days': total_days,
            'phase': phase,
            'phase_day': phase_day,
            'progress_pct': progress_pct,
            'total_readings': total_readings,
            'phase_transition': phase_transition,
            'season_complete': season_complete,
        }

    # ============ Legacy Milestones (kept for backward compat) ============

    def compute_milestones(self) -> List[Dict[str, Any]]:
        """Check milestone achievements (5 milestones).
        Public wrapper that fetches its own data for direct API calls."""
        total_readings = self.db.count_readings()
        first_timestamp = self.db.get_first_reading_timestamp()
        all_summaries = self.db.get_daily_summaries(days=365)
        baselines = self.db.get_all_baselines()
        return self._compute_milestones_with_data(
            total_readings, first_timestamp, all_summaries, baselines)

    def _compute_milestones_with_data(self, total_readings: int,
                                       first_timestamp: Optional[str],
                                       all_summaries: List[Dict],
                                       baselines: Dict = None) -> List[Dict[str, Any]]:
        """Compute milestones from pre-fetched data (avoids redundant queries)."""
        if baselines is None:
            baselines = self.db.get_all_baselines()

        milestones = []

        milestones.append({
            'id': 'first_reading', 'name': 'First Reading',
            'description': 'Recorded your first voice sample',
            'achieved': total_readings >= 1,
            'achieved_date': first_timestamp,
            'icon': '\U0001F3A4'
        })

        is_calibrated = len(baselines) >= 6 and all(b.get('samples', 0) >= 10 for b in baselines.values())
        milestones.append({
            'id': 'calibrated', 'name': 'Calibrated',
            'description': 'Completed personal baseline calibration',
            'achieved': is_calibrated, 'achieved_date': None, 'icon': '\U0001F3AF'
        })

        calm_days = [s for s in all_summaries if s.get('time_in_calm_min', 0) > 60]
        milestones.append({
            'id': 'calm_champion', 'name': 'Calm Champion',
            'description': 'Spent 60+ minutes in Calm zone in a single day',
            'achieved': len(calm_days) > 0,
            'achieved_date': calm_days[0]['date'] if calm_days else None,
            'icon': '\U0001F9D8'
        })

        meeting_days = [s for s in all_summaries
                       if s.get('total_meetings', 0) >= 5 and s.get('avg_stress', 100) < 50]
        milestones.append({
            'id': 'meeting_survivor', 'name': 'Meeting Survivor',
            'description': '5+ meetings in a day with stress < 50',
            'achieved': len(meeting_days) > 0,
            'achieved_date': meeting_days[0]['date'] if meeting_days else None,
            'icon': '\U0001F4BC'
        })

        zen_achieved = False
        zen_date = None
        if len(all_summaries) >= 3:
            sorted_summaries = sorted(all_summaries, key=lambda s: s['date'])
            for i in range(len(sorted_summaries) - 2):
                if (sorted_summaries[i].get('avg_stress', 100) < 30 and
                    sorted_summaries[i+1].get('avg_stress', 100) < 30 and
                    sorted_summaries[i+2].get('avg_stress', 100) < 30):
                    zen_achieved = True
                    zen_date = sorted_summaries[i+2]['date']
                    break

        milestones.append({
            'id': 'zen_master', 'name': 'Zen Master',
            'description': '3 consecutive days with stress < 30',
            'achieved': zen_achieved, 'achieved_date': zen_date, 'icon': '\U0001F31F'
        })

        return milestones

    def get_engagement_summary(self) -> Dict[str, Any]:
        """Return full engagement summary using efficient targeted queries."""
        total_readings = self.db.count_readings()
        first_timestamp = self.db.get_first_reading_timestamp()
        all_summaries = self.db.get_daily_summaries(days=365)
        baselines = self.db.get_all_baselines()
        total_meetings = sum(s.get('total_meetings', 0) for s in all_summaries)

        return {
            'milestones': self._compute_milestones_with_data(
                total_readings, first_timestamp, all_summaries, baselines),
            'total_readings': total_readings,
            'total_days': len(all_summaries),
            'total_meetings': total_meetings
        }

    def export_readings_csv(self, start_date: str = None, end_date: str = None) -> str:
        """Export readings to CSV string"""
        if start_date and end_date:
            readings = self.db.get_readings(start_time=start_date, end_time=end_date, limit=10000)
        else:
            readings = self.db.get_readings(limit=10000)

        if not readings:
            return "No data to export"

        output = io.StringIO()
        fieldnames = list(readings[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for reading in readings:
            writer.writerow(reading)
        return output.getvalue()

    def export_summaries_csv(self, days: int = 30) -> str:
        """Export daily summaries to CSV string"""
        summaries = self.db.get_daily_summaries(days=days)

        if not summaries:
            return "No data to export"

        output = io.StringIO()
        fieldnames = list(summaries[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary)
        return output.getvalue()
