import logging
"""
Engagement tracker with streaks, milestones, grove, waypoints, rhythm rings
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

    def compute_streak(self) -> int:
        """Compute current daily streak (consecutive days with readings)"""
        summaries = self.db.get_daily_summaries(days=365)
        return self._compute_streak_from_summaries(summaries)

    def _compute_streak_from_summaries(self, summaries: List[Dict]) -> int:
        """Compute streak from pre-fetched summaries."""
        if not summaries:
            return 0

        # Sort by date descending (most recent first)
        summaries = sorted(summaries, key=lambda s: s['date'], reverse=True)

        # Check if today has data
        today = date.today().isoformat()
        if summaries[0]['date'] != today:
            return 0

        # Count consecutive days backwards from today
        streak = 0
        current_date = date.today()

        for summary in summaries:
            summary_date = date.fromisoformat(summary['date'])
            if summary_date == current_date:
                streak += 1
                current_date -= timedelta(days=1)
            elif summary_date < current_date:
                break

        return streak

    # ============ Grove (Feature #2) ============

    def update_grove(self) -> Dict[str, Any]:
        """Update grove state: grow trees for active days, wilt for missed days."""
        summaries = self.db.get_daily_summaries(days=90)
        if not summaries:
            return self.get_grove_state()

        summary_dates = {s['date'] for s in summaries}
        trees = self.db.get_grove_trees(limit=90)
        existing_dates = {t['date'] for t in trees}

        # Ensure rainfall exists
        rainfall = int(self.db.get_user_state('rainfall', '1'))  # Start with 1 free

        today = date.today()

        # Add trees for days with data
        for s in summaries:
            d = s['date']
            if d not in existing_dates:
                # Compute growth stage based on streak at that date
                stage = 1
                self.db.add_grove_tree(d, 'growing', stage)

        # Check for missed days (gaps) — wilt trees
        if summaries:
            sorted_dates = sorted(summary_dates)
            first = date.fromisoformat(sorted_dates[0])
            for i in range((today - first).days + 1):
                check_date = (first + timedelta(days=i)).isoformat()
                if check_date not in summary_dates and check_date not in existing_dates:
                    if check_date <= today.isoformat():
                        self.db.add_grove_tree(check_date, 'wilted', 0)

        # Update growth stages based on streak length (never downgrade bonus stages)
        trees = self.db.get_grove_trees(limit=90)
        for tree in trees:
            if tree['tree_state'] == 'growing':
                d = date.fromisoformat(tree['date'])
                days_alive = (today - d).days
                if days_alive >= 30:
                    stage = 4  # Full canopy
                elif days_alive >= 7:
                    stage = 3  # Blooming
                elif days_alive >= 3:
                    stage = 2  # Growing
                else:
                    stage = 1  # Seedling
                # Never downgrade a tree (bonus trees from quests may have higher stages)
                stage = max(stage, tree['growth_stage'])
                if stage != tree['growth_stage']:
                    self.db.update_grove_tree(tree['date'], stage=stage)

        # Earn rainfall: 1 per 5 readings today
        today_readings = self.db.get_today_readings()
        earned_today = len(today_readings) // 5
        already_earned = int(self.db.get_user_state('rainfall_earned_today', '0'))
        if earned_today > already_earned:
            new_rainfall = rainfall + (earned_today - already_earned)
            self.db.set_user_state('rainfall', str(new_rainfall))
            self.db.set_user_state('rainfall_earned_today', str(earned_today))

        return self.get_grove_state()

    def get_grove_state(self) -> Dict[str, Any]:
        trees = self.db.get_grove_trees(limit=90)
        rainfall = int(self.db.get_user_state('rainfall', '1'))
        wilted_count = sum(1 for t in trees if t['tree_state'] == 'wilted')
        growing_count = sum(1 for t in trees if t['tree_state'] == 'growing')
        return {
            'trees': trees,
            'rainfall': rainfall,
            'wilted_count': wilted_count,
            'growing_count': growing_count,
            'total_trees': len(trees),
        }

    def revive_tree(self, tree_date: str) -> Dict[str, Any]:
        """Use rainfall to revive a wilted tree."""
        rainfall = int(self.db.get_user_state('rainfall', '0'))
        if rainfall <= 0:
            return {'success': False, 'message': 'No rainfall available'}

        trees = self.db.get_grove_trees(limit=90)
        target = next((t for t in trees if t['date'] == tree_date and t['tree_state'] == 'wilted'), None)
        if not target:
            return {'success': False, 'message': 'No wilted tree on that date'}

        self.db.update_grove_tree(tree_date, state='growing', stage=1, revived=1)
        self.db.set_user_state('rainfall', str(rainfall - 1))
        return {'success': True, 'rainfall_remaining': rainfall - 1}

    # ============ Waypoints (Feature #4) ============

    # Waypoint lambdas: (summaries, reading_count: int, state) -> bool
    WAYPOINTS = [
        # Tier: Seedling (Days 1-3) - first 2 pre-completed
        {'id': 'wp_welcome', 'name': 'Welcome', 'desc': 'Opened Lucid for the first time', 'tier': 'Seedling', 'order': 1, 'auto': True},
        {'id': 'wp_first_voice', 'name': 'First Voice', 'desc': 'Recorded your first voice sample', 'tier': 'Seedling', 'order': 2, 'auto': True},
        {'id': 'wp_3_readings', 'name': 'Getting Started', 'desc': 'Complete 3 voice readings', 'tier': 'Seedling', 'order': 3, 'check': lambda s, rc, st: rc >= 3},
        {'id': 'wp_first_calm', 'name': 'First Calm', 'desc': 'Reach the Calm zone', 'tier': 'Seedling', 'order': 4, 'check': lambda s, rc, st: any(d.get('time_in_calm_min', 0) > 0 for d in s)},
        {'id': 'wp_day3', 'name': 'Day 3', 'desc': 'Use Lucid for 3 days', 'tier': 'Seedling', 'order': 5, 'check': lambda s, rc, st: len(s) >= 3},

        # Tier: Sapling (Days 4-7)
        {'id': 'wp_10_readings', 'name': '10 Readings', 'desc': 'Complete 10 voice readings', 'tier': 'Sapling', 'order': 6, 'check': lambda s, rc, st: rc >= 10},
        {'id': 'wp_calibrated', 'name': 'Calibrated', 'desc': 'Personal baseline established', 'tier': 'Sapling', 'order': 7, 'check': lambda s, rc, st: st.get('calibrated', False)},
        {'id': 'wp_5_calm_min', 'name': '5 Min Calm', 'desc': '5+ minutes in Calm zone in one day', 'tier': 'Sapling', 'order': 8, 'check': lambda s, rc, st: any(d.get('time_in_calm_min', 0) >= 5 for d in s)},
        {'id': 'wp_first_meeting', 'name': 'Meeting Tracked', 'desc': 'Track your first meeting', 'tier': 'Sapling', 'order': 9, 'check': lambda s, rc, st: any(d.get('total_meetings', 0) >= 1 for d in s)},
        {'id': 'wp_week', 'name': 'One Week', 'desc': '7-day streak', 'tier': 'Sapling', 'order': 10, 'check': lambda s, rc, st: st.get('streak', 0) >= 7},

        # Tier: Young Tree (Days 8-14)
        {'id': 'wp_25_readings', 'name': '25 Readings', 'desc': 'Complete 25 voice readings', 'tier': 'Young Tree', 'order': 11, 'check': lambda s, rc, st: rc >= 25},
        {'id': 'wp_calm_champ', 'name': 'Calm Champion', 'desc': '60+ minutes in Calm zone in one day', 'tier': 'Young Tree', 'order': 12, 'check': lambda s, rc, st: any(d.get('time_in_calm_min', 0) >= 60 for d in s)},
        {'id': 'wp_low_stress_day', 'name': 'Low Stress Day', 'desc': 'Average stress below 30 for a full day', 'tier': 'Young Tree', 'order': 13, 'check': lambda s, rc, st: any(d.get('avg_stress', 100) < 30 for d in s)},
        {'id': 'wp_rings_closed', 'name': 'Rings Closed', 'desc': 'Close all 3 Rhythm Rings in one day', 'tier': 'Young Tree', 'order': 14, 'check': lambda s, rc, st: st.get('rings_closed', False)},
        {'id': 'wp_fortnight', 'name': 'Two Weeks', 'desc': '14-day streak', 'tier': 'Young Tree', 'order': 15, 'check': lambda s, rc, st: st.get('streak', 0) >= 14},

        # Tier: Mature Tree (Days 15-30)
        {'id': 'wp_50_readings', 'name': 'Half Century', 'desc': 'Complete 50 voice readings', 'tier': 'Mature Tree', 'order': 16, 'check': lambda s, rc, st: rc >= 50},
        {'id': 'wp_meeting_survivor', 'name': 'Meeting Survivor', 'desc': '5+ meetings, stress < 50', 'tier': 'Mature Tree', 'order': 17, 'check': lambda s, rc, st: any(d.get('total_meetings', 0) >= 5 and d.get('avg_stress', 100) < 50 for d in s)},
        {'id': 'wp_recovery_pro', 'name': 'Recovery Pro', 'desc': 'Peak Recovery of 30+ points', 'tier': 'Mature Tree', 'order': 18, 'check': lambda s, rc, st: st.get('peak_recovery', 0) >= 30},
        {'id': 'wp_3_day_zen', 'name': 'Zen Master', 'desc': '3 consecutive low-stress days', 'tier': 'Mature Tree', 'order': 19, 'check': lambda s, rc, st: st.get('zen_achieved', False)},
        {'id': 'wp_month', 'name': 'One Month', 'desc': '30-day streak', 'tier': 'Mature Tree', 'order': 20, 'check': lambda s, rc, st: st.get('streak', 0) >= 30},

        # Tier: Old Growth (Days 31-90)
        {'id': 'wp_100_readings', 'name': 'Centurion', 'desc': 'Complete 100 voice readings', 'tier': 'Old Growth', 'order': 21, 'check': lambda s, rc, st: rc >= 100},
        {'id': 'wp_canopy_90', 'name': 'Health 90', 'desc': 'Achieve a Health Score of 90+', 'tier': 'Old Growth', 'order': 22, 'check': lambda s, rc, st: st.get('best_canopy', 0) >= 90},
        {'id': 'wp_5_ring_days', 'name': 'Ring Master', 'desc': 'Close all rings 5 different days', 'tier': 'Old Growth', 'order': 23, 'check': lambda s, rc, st: st.get('ring_close_days', 0) >= 5},
        {'id': 'wp_10_echoes', 'name': 'Pattern Seeker', 'desc': 'Discover 10 Echoes', 'tier': 'Old Growth', 'order': 24, 'check': lambda s, rc, st: st.get('echo_count', 0) >= 10},
        {'id': 'wp_60_days', 'name': 'Two Months', 'desc': '60-day streak', 'tier': 'Old Growth', 'order': 25, 'check': lambda s, rc, st: st.get('streak', 0) >= 60},

        # Tier: Ancient (90+)
        {'id': 'wp_250_readings', 'name': 'Voice Veteran', 'desc': '250 voice readings', 'tier': 'Ancient', 'order': 26, 'check': lambda s, rc, st: rc >= 250},
        {'id': 'wp_full_grove', 'name': 'Full Grove', 'desc': '30 healthy trees in your Grove', 'tier': 'Ancient', 'order': 27, 'check': lambda s, rc, st: st.get('growing_trees', 0) >= 30},
        {'id': 'wp_all_records', 'name': 'Veteran Listener', 'desc': '200+ voice readings', 'tier': 'Ancient', 'order': 28, 'check': lambda s, rc, st: rc >= 200},
        {'id': 'wp_90_days', 'name': 'Quarter Year', 'desc': '90-day streak', 'tier': 'Ancient', 'order': 29, 'check': lambda s, rc, st: st.get('streak', 0) >= 90},
        {'id': 'wp_ancient', 'name': 'Ancient Grove', 'desc': 'Use Lucid for 90+ days', 'tier': 'Ancient', 'order': 30, 'check': lambda s, rc, st: len(s) >= 90},
    ]

    def compute_waypoints(self) -> Dict[str, Any]:
        """Compute all 30 waypoints with progress."""
        reading_count = self.db.count_readings()
        all_summaries = self.db.get_daily_summaries(days=365)
        baselines = self.db.get_all_baselines()
        streak = self._compute_streak_from_summaries(all_summaries)
        grove = self.get_grove_state()
        echoes = self.db.get_echoes(limit=100)

        # Build state dict for lambda checks
        is_calibrated = len(baselines) >= 6 and all(b.get('samples', 0) >= 10 for b in baselines.values())

        # Check zen
        zen_achieved = False
        sorted_sums = sorted(all_summaries, key=lambda s: s['date'])
        for i in range(len(sorted_sums) - 2):
            if (sorted_sums[i].get('avg_stress', 100) < 30 and
                sorted_sums[i+1].get('avg_stress', 100) < 30 and
                sorted_sums[i+2].get('avg_stress', 100) < 30):
                zen_achieved = True
                break

        # Compute peak recovery from today's readings
        peak_recovery = 0
        today_readings = self.db.get_today_readings()
        if len(today_readings) >= 2:
            sorted_readings = list(reversed(today_readings))
            for i in range(1, len(sorted_readings)):
                prev_stress = sorted_readings[i-1].get('stress_score', 0)
                curr_stress = sorted_readings[i].get('stress_score', 0)
                drop = prev_stress - curr_stress
                peak_recovery = max(peak_recovery, drop)

        # Best canopy from DB
        best_canopy = 0
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT MAX(score) as max_score FROM canopy_scores")
            row = cursor.fetchone()
            if row and row['max_score'] is not None:
                best_canopy = row['max_score']
        except Exception as e:
            logger.debug("Canopy score query failed: %s", e)

        state = {
            'streak': streak,
            'calibrated': is_calibrated,
            'zen_achieved': zen_achieved,
            'peak_recovery': peak_recovery,
            'best_canopy': best_canopy,
            'growing_trees': grove['growing_count'],
            'echo_count': len(echoes),
            'rings_closed': False,  # Computed in rings
            'ring_close_days': 0,
        }

        waypoints = []
        for wp in self.WAYPOINTS:
            achieved = False
            if wp.get('auto'):
                achieved = True  # Pre-completed (endowed progress)
            elif wp.get('check'):
                try:
                    achieved = wp['check'](all_summaries, reading_count, state)
                except Exception as e:
                    logger.debug("Waypoint check failed for %s: %s", wp.get('id', '?'), e)
                    achieved = False

            # Persist to DB
            self.db.upsert_achievement(wp['id'], wp['name'], wp['desc'], wp['tier'], achieved, wp['order'])

            waypoints.append({
                'id': wp['id'],
                'name': wp['name'],
                'description': wp['desc'],
                'tier': wp['tier'],
                'achieved': achieved,
                'sort_order': wp['order'],
            })

        # Group by tier
        tiers = ['Seedling', 'Sapling', 'Young Tree', 'Mature Tree', 'Old Growth', 'Ancient']
        grouped = {t: [w for w in waypoints if w['tier'] == t] for t in tiers}
        total_achieved = sum(1 for w in waypoints if w['achieved'])

        return {
            'waypoints': waypoints,
            'by_tier': grouped,
            'total': len(waypoints),
            'total_readings': reading_count,
            'achieved': total_achieved,
            'progress_pct': round(total_achieved / len(waypoints) * 100),
        }

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

    # ============ Legacy Milestones (kept for backward compat) ============

    def compute_milestones(self) -> List[Dict[str, Any]]:
        """Check milestone achievements (legacy 7 milestones).
        Public wrapper that fetches its own data for direct API calls."""
        total_readings = self.db.count_readings()
        first_timestamp = self.db.get_first_reading_timestamp()
        all_summaries = self.db.get_daily_summaries(days=365)
        baselines = self.db.get_all_baselines()
        streak = self._compute_streak_from_summaries(all_summaries)
        return self._compute_milestones_with_data(
            total_readings, first_timestamp, all_summaries, baselines, streak)

    def _compute_milestones_with_data(self, total_readings: int,
                                       first_timestamp: Optional[str],
                                       all_summaries: List[Dict],
                                       baselines: Dict = None,
                                       streak: int = 0) -> List[Dict[str, Any]]:
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

        milestones.append({
            'id': 'week_warrior', 'name': 'Week Warrior',
            'description': '7-day streak', 'achieved': streak >= 7,
            'achieved_date': None, 'icon': '\U0001F525'
        })

        milestones.append({
            'id': 'fortnight_strong', 'name': 'Fortnight Strong',
            'description': '14-day streak', 'achieved': streak >= 14,
            'achieved_date': None, 'icon': '\U0001F4AA'
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
        streak = self._compute_streak_from_summaries(all_summaries)
        total_meetings = sum(s.get('total_meetings', 0) for s in all_summaries)

        return {
            'streak': streak,
            'milestones': self._compute_milestones_with_data(
                total_readings, first_timestamp, all_summaries, baselines, streak),
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
