"""
Pattern Detector for Echoes feature + Eureka Engine
Discovers statistical patterns and deeper correlations in user's voice data
"""
from typing import Dict, List, Any, Optional
from datetime import date, datetime, timedelta
import math
import statistics


class PatternDetector:
    """Detects patterns in voice data for the Echoes feature."""

    def __init__(self, db):
        self.db = db

    def detect_patterns(self) -> List[Dict[str, Any]]:
        """Run all pattern detectors. Returns list of new discoveries."""
        summaries = self.db.get_daily_summaries(days=90)
        if len(summaries) < 7:
            return []

        discoveries = []
        existing = {e['pattern_type'] for e in self.db.get_echoes(limit=200)}

        # Collect candidates from all detectors
        all_candidates = []
        all_candidates.extend(self._detect_day_of_week(summaries))        # 1. Day-of-week
        all_candidates.extend(self._detect_trends(summaries))              # 2. Trends
        all_candidates.extend(self._detect_meeting_impact(summaries))      # 3. Meeting impact
        all_candidates.extend(self._detect_time_of_day())                  # 4. Time-of-day
        all_candidates.extend(self._detect_milestones(summaries))          # 5. Milestones
        all_candidates.extend(self._detect_multi_week_trends(summaries))   # 6. Eureka: Burnout trajectory
        all_candidates.extend(self._detect_recovery_patterns())            # 7. Eureka: Recovery
        all_candidates.extend(self._detect_compound_effects(summaries))    # 8. Eureka: Compound effects
        all_candidates.extend(self._detect_anomalies(summaries))           # 9. Eureka: Anomaly detection
        all_candidates.extend(self._detect_back_to_back_meetings())        # 10. Eureka: Back-to-back meetings

        # Filter to only new discoveries
        for p in all_candidates:
            if p['pattern_type'] not in existing:
                discoveries.append(p)

        # Batch-insert all new echoes in a single transaction
        self.db.batch_add_echoes(discoveries)

        return discoveries

    def _detect_day_of_week(self, summaries: List[Dict]) -> List[Dict]:
        """Find which day of week is calmest/most stressed."""
        patterns = []
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        # Group by day of week
        by_dow = {i: [] for i in range(7)}
        for s in summaries:
            d = date.fromisoformat(s['date'])
            by_dow[d.weekday()].append(s)

        # Find calmest day
        avg_stress_by_dow = {}
        for dow, days in by_dow.items():
            if len(days) >= 2:
                avg_stress_by_dow[dow] = sum(d.get('avg_stress', 50) for d in days) / len(days)

        if len(avg_stress_by_dow) >= 3:
            calmest_dow = min(avg_stress_by_dow, key=avg_stress_by_dow.get)
            most_stressed_dow = max(avg_stress_by_dow, key=avg_stress_by_dow.get)
            diff = avg_stress_by_dow[most_stressed_dow] - avg_stress_by_dow[calmest_dow]

            if diff >= 10:
                patterns.append({
                    'pattern_type': 'dow_calmest',
                    'message': f'{day_names[calmest_dow]}s are your calmest day (avg stress {avg_stress_by_dow[calmest_dow]:.0f} vs {avg_stress_by_dow[most_stressed_dow]:.0f} on {day_names[most_stressed_dow]}s)',
                    'detail': f'Based on {len(summaries)} days of data',
                    'tier': 'eureka',
                })

        # Find best mood day
        avg_mood_by_dow = {}
        for dow, days in by_dow.items():
            if len(days) >= 2:
                avg_mood_by_dow[dow] = sum(d.get('avg_mood', 50) for d in days) / len(days)

        if len(avg_mood_by_dow) >= 3:
            best_mood_dow = max(avg_mood_by_dow, key=avg_mood_by_dow.get)
            if avg_mood_by_dow[best_mood_dow] > 60:
                patterns.append({
                    'pattern_type': 'dow_best_mood',
                    'message': f'Your mood peaks on {day_names[best_mood_dow]}s (avg {avg_mood_by_dow[best_mood_dow]:.0f}/100)',
                })

        return patterns

    def _detect_trends(self, summaries: List[Dict]) -> List[Dict]:
        """Detect multi-week trends."""
        patterns = []
        if len(summaries) < 14:
            return patterns

        sorted_s = sorted(summaries, key=lambda s: s['date'])
        first_week = sorted_s[:7]
        last_week = sorted_s[-7:]

        first_stress = sum(s.get('avg_stress', 50) for s in first_week) / 7
        last_stress = sum(s.get('avg_stress', 50) for s in last_week) / 7
        change = last_stress - first_stress

        if change <= -10:
            patterns.append({
                'pattern_type': f'trend_stress_down_{len(summaries)}',
                'message': f'Your stress has dropped {abs(change):.0f} points over the past {len(summaries)} days',
                'detail': f'From {first_stress:.0f} to {last_stress:.0f} average'
            })
        elif change >= 10:
            patterns.append({
                'pattern_type': f'trend_stress_up_{len(summaries)}',
                'message': f'Your stress has risen {change:.0f} points over the past {len(summaries)} days. Consider adding recovery time.',
                'detail': f'From {first_stress:.0f} to {last_stress:.0f} average'
            })

        # Calm time trend
        first_calm = sum(s.get('time_in_calm_min', 0) for s in first_week) / 7
        last_calm = sum(s.get('time_in_calm_min', 0) for s in last_week) / 7
        if last_calm > first_calm + 10:
            patterns.append({
                'pattern_type': f'trend_calm_up_{len(summaries)}',
                'message': f'Your daily calm time has increased by {last_calm - first_calm:.0f} minutes per day',
            })

        return patterns

    def _detect_meeting_impact(self, summaries: List[Dict]) -> List[Dict]:
        """Detect how meetings affect stress."""
        patterns = []

        meeting_days = [s for s in summaries if s.get('total_meetings', 0) >= 3]
        no_meeting_days = [s for s in summaries if s.get('total_meetings', 0) == 0]

        if len(meeting_days) >= 3 and len(no_meeting_days) >= 3:
            meeting_stress = sum(s.get('avg_stress', 50) for s in meeting_days) / len(meeting_days)
            no_meeting_stress = sum(s.get('avg_stress', 50) for s in no_meeting_days) / len(no_meeting_days)
            diff = meeting_stress - no_meeting_stress

            if diff >= 8:
                patterns.append({
                    'pattern_type': 'meeting_impact_stress',
                    'message': f'Meeting-heavy days raise your stress by {diff:.0f} points on average',
                    'detail': f'Meeting days: {meeting_stress:.0f} vs No-meeting days: {no_meeting_stress:.0f}'
                })
            elif diff <= -5:
                patterns.append({
                    'pattern_type': 'meeting_impact_positive',
                    'message': f'Interestingly, meeting days are LESS stressful for you ({meeting_stress:.0f} vs {no_meeting_stress:.0f})',
                })

        return patterns

    def _detect_time_of_day(self) -> List[Dict]:
        """Detect time-of-day patterns from individual readings."""
        patterns = []
        readings = self.db.get_readings(limit=5000)
        if len(readings) < 20:
            return patterns

        # Group by time bucket (morning, midday, afternoon, evening)
        buckets = {'morning': [], 'midday': [], 'afternoon': [], 'evening': []}
        for r in readings:
            try:
                ts = datetime.fromisoformat(r['timestamp'])
                h = ts.hour
                if 6 <= h < 10:
                    buckets['morning'].append(r)
                elif 10 <= h < 13:
                    buckets['midday'].append(r)
                elif 13 <= h < 17:
                    buckets['afternoon'].append(r)
                elif 17 <= h < 22:
                    buckets['evening'].append(r)
            except (ValueError, TypeError):
                continue

        # Find stress by time bucket
        stress_by_bucket = {}
        for name, rs in buckets.items():
            if len(rs) >= 5:
                stress_by_bucket[name] = sum(r.get('stress_score', 50) for r in rs) / len(rs)

        if len(stress_by_bucket) >= 2:
            calmest = min(stress_by_bucket, key=stress_by_bucket.get)
            most_stressed = max(stress_by_bucket, key=stress_by_bucket.get)
            diff = stress_by_bucket[most_stressed] - stress_by_bucket[calmest]

            if diff >= 10:
                patterns.append({
                    'pattern_type': 'tod_stress',
                    'message': f'Your {calmest} is your calmest time of day (stress {stress_by_bucket[calmest]:.0f} vs {stress_by_bucket[most_stressed]:.0f} in the {most_stressed})',
                })

        return patterns

    def _detect_milestones(self, summaries: List[Dict]) -> List[Dict]:
        """Detect data volume milestones."""
        patterns = []
        readings = self.db.get_readings(limit=10000)
        total = len(readings)

        milestones = [50, 100, 200, 500, 1000]
        for m in milestones:
            if total >= m:
                total_hours = sum(r.get('speech_duration_sec', 0) for r in readings) / 3600
                patterns.append({
                    'pattern_type': f'milestone_{m}_readings',
                    'message': f"You've completed {m} voice readings — that's {total_hours:.1f} hours of self-awareness",
                })

        return patterns

    # ================================================================
    #  Eureka Engine — Deeper Correlations
    # ================================================================

    def _detect_multi_week_trends(self, summaries: List[Dict]) -> List[Dict]:
        """Detect slow-moving multi-week stress trajectories (burnout warning)."""
        patterns = []
        if len(summaries) < 28:
            return patterns

        sorted_s = sorted(summaries, key=lambda s: s['date'])

        # Linear regression on weekly averages over 4 weeks
        weeks = []
        for i in range(0, len(sorted_s), 7):
            chunk = sorted_s[i:i + 7]
            if len(chunk) >= 5:
                avg = sum(s.get('avg_stress', 50) or 50 for s in chunk) / len(chunk)
                weeks.append(avg)

        if len(weeks) >= 4:
            # Simple slope calculation
            n = len(weeks)
            x_mean = (n - 1) / 2
            y_mean = sum(weeks) / n
            numerator = sum((i - x_mean) * (w - y_mean) for i, w in enumerate(weeks))
            denominator = sum((i - x_mean) ** 2 for i in range(n))

            if denominator > 0:
                slope = numerator / denominator  # stress points per week

                if slope >= 3:
                    total_weeks = len(weeks)
                    patterns.append({
                        'pattern_type': f'eureka_burnout_trajectory_{total_weeks}w',
                        'message': f'Your stress has been climbing ~{slope:.0f} points per week for {total_weeks} weeks. This is a burnout trajectory.',
                        'detail': f'Weekly averages: {", ".join(f"{w:.0f}" for w in weeks[-4:])}',
                        'tier': 'eureka',
                    })
                elif slope <= -3:
                    patterns.append({
                        'pattern_type': f'eureka_recovery_trajectory_{len(weeks)}w',
                        'message': f'Great trend: your stress has been dropping ~{abs(slope):.0f} points per week for {len(weeks)} weeks.',
                        'detail': f'Weekly averages: {", ".join(f"{w:.0f}" for w in weeks[-4:])}',
                        'tier': 'eureka',
                    })

        return patterns

    def _detect_recovery_patterns(self) -> List[Dict]:
        """Detect how fast user recovers from stress spikes, comparing AM vs PM."""
        patterns = []
        readings = self.db.get_readings(limit=5000)
        if len(readings) < 50:
            return patterns

        # Group readings by date
        by_date = {}
        for r in readings:
            try:
                ts = datetime.fromisoformat(r['timestamp'])
                d = ts.date().isoformat()
                if d not in by_date:
                    by_date[d] = []
                by_date[d].append(r)
            except (ValueError, TypeError):
                continue

        # Measure recovery speed: find stress peaks, then time to return to baseline
        am_recoveries = []
        pm_recoveries = []

        for d, day_readings in by_date.items():
            if len(day_readings) < 4:
                continue

            sorted_r = sorted(day_readings, key=lambda x: x['timestamp'])
            for i in range(1, len(sorted_r) - 1):
                stress = sorted_r[i].get('stress_score', 0) or 0
                prev_stress = sorted_r[i - 1].get('stress_score', 0) or 0
                next_stress = sorted_r[i + 1].get('stress_score', 0) or 0

                # Peak: higher than neighbors by 15+ points
                if stress >= prev_stress + 15 and stress >= next_stress + 10:
                    drop = stress - next_stress
                    try:
                        ts = datetime.fromisoformat(sorted_r[i]['timestamp'])
                        if ts.hour < 13:
                            am_recoveries.append(drop)
                        else:
                            pm_recoveries.append(drop)
                    except (ValueError, TypeError):
                        continue

        if len(am_recoveries) >= 3 and len(pm_recoveries) >= 3:
            am_avg = sum(am_recoveries) / len(am_recoveries)
            pm_avg = sum(pm_recoveries) / len(pm_recoveries)
            diff = pm_avg - am_avg

            if abs(diff) >= 5:
                faster = "afternoon" if pm_avg > am_avg else "morning"
                patterns.append({
                    'pattern_type': 'eureka_recovery_speed',
                    'message': f'You recover from stress spikes faster in the {faster} (avg {max(am_avg, pm_avg):.0f} point drop vs {min(am_avg, pm_avg):.0f})',
                    'detail': f'Based on {len(am_recoveries)} AM and {len(pm_recoveries)} PM stress peaks',
                    'tier': 'eureka',
                })

        return patterns

    def _detect_compound_effects(self, summaries: List[Dict]) -> List[Dict]:
        """Correlate morning state with daily outcomes."""
        patterns = []
        if len(summaries) < 14:
            return patterns

        # Group days by whether they started calm (first reading calm zone)
        calm_start_days = []
        non_calm_start_days = []

        for s in summaries:
            d = date.fromisoformat(s['date'])
            day_readings = self.db.get_readings_for_date(d)
            if not day_readings:
                continue

            # First reading is last in list (DESC order)
            first_reading = day_readings[-1] if day_readings else None
            if not first_reading:
                continue

            first_zone = first_reading.get('zone', 'steady')
            peak_stress = s.get('peak_stress', 50) or 50

            if first_zone == 'calm':
                calm_start_days.append(peak_stress)
            else:
                non_calm_start_days.append(peak_stress)

        if len(calm_start_days) >= 3 and len(non_calm_start_days) >= 3:
            calm_peak = sum(calm_start_days) / len(calm_start_days)
            non_calm_peak = sum(non_calm_start_days) / len(non_calm_start_days)
            diff = non_calm_peak - calm_peak

            if diff >= 10:
                pct = round(diff / non_calm_peak * 100) if non_calm_peak > 0 else 0
                patterns.append({
                    'pattern_type': 'eureka_morning_state',
                    'message': f'Days you start calm have {pct}% lower peak stress ({calm_peak:.0f} vs {non_calm_peak:.0f})',
                    'detail': f'Based on {len(calm_start_days)} calm-start vs {len(non_calm_start_days)} other days',
                    'tier': 'eureka',
                })

        return patterns

    def _detect_anomalies(self, summaries: List[Dict]) -> List[Dict]:
        """Flag today if it's unusual compared to same-weekday history."""
        patterns = []
        if len(summaries) < 14:
            return patterns

        today = date.today()
        today_dow = today.weekday()

        # Get today's summary
        today_summary = None
        for s in summaries:
            if s['date'] == today.isoformat():
                today_summary = s
                break

        if not today_summary:
            return patterns

        # Get same-weekday history (excluding today)
        same_dow = []
        for s in summaries:
            d = date.fromisoformat(s['date'])
            if d.weekday() == today_dow and d != today:
                same_dow.append(s)

        if len(same_dow) < 3:
            return patterns

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        today_stress = today_summary.get('avg_stress', 50) or 50
        hist_stresses = [s.get('avg_stress', 50) or 50 for s in same_dow]
        hist_mean = sum(hist_stresses) / len(hist_stresses)

        if len(hist_stresses) >= 2:
            try:
                hist_std = statistics.stdev(hist_stresses)
            except statistics.StatisticsError:
                hist_std = 0

            if hist_std > 0:
                z = (today_stress - hist_mean) / hist_std
                if abs(z) >= 1.5:
                    direction = "higher" if z > 0 else "lower"
                    patterns.append({
                        'pattern_type': f'eureka_anomaly_{today.isoformat()}',
                        'message': f"Today's stress ({today_stress:.0f}) is unusually {direction} compared to your typical {day_names[today_dow]}s (avg {hist_mean:.0f})",
                        'detail': f'Z-score: {z:.1f} based on {len(same_dow)} previous {day_names[today_dow]}s',
                        'tier': 'eureka',
                    })

        return patterns

    def _detect_back_to_back_meetings(self) -> List[Dict]:
        """Compare stress from clustered vs spaced meeting readings."""
        patterns = []
        readings = self.db.get_readings(limit=5000)
        if len(readings) < 30:
            return patterns

        # Find meeting readings
        meeting_readings = [r for r in readings if r.get('meeting_detected') == 1]
        if len(meeting_readings) < 10:
            return patterns

        # Sort by timestamp
        sorted_m = sorted(meeting_readings, key=lambda r: r.get('timestamp', ''))

        clustered_stress = []
        isolated_stress = []

        for i, r in enumerate(sorted_m):
            try:
                ts = datetime.fromisoformat(r['timestamp'])
                stress = r.get('stress_score', 50) or 50

                # Check if previous meeting reading was within 10 minutes
                is_clustered = False
                if i > 0:
                    prev_ts = datetime.fromisoformat(sorted_m[i - 1]['timestamp'])
                    gap_min = (ts - prev_ts).total_seconds() / 60
                    if gap_min < 10:
                        is_clustered = True

                # Check if next meeting reading is within 10 minutes
                if i < len(sorted_m) - 1:
                    next_ts = datetime.fromisoformat(sorted_m[i + 1]['timestamp'])
                    gap_min = (next_ts - ts).total_seconds() / 60
                    if gap_min < 10:
                        is_clustered = True

                if is_clustered:
                    clustered_stress.append(stress)
                else:
                    isolated_stress.append(stress)
            except (ValueError, TypeError):
                continue

        if len(clustered_stress) >= 5 and len(isolated_stress) >= 5:
            avg_clustered = sum(clustered_stress) / len(clustered_stress)
            avg_isolated = sum(isolated_stress) / len(isolated_stress)
            diff = avg_clustered - avg_isolated

            if diff >= 8:
                pct = round(diff / avg_isolated * 100) if avg_isolated > 0 else 0
                patterns.append({
                    'pattern_type': 'eureka_back_to_back',
                    'message': f'Back-to-back meetings raise your stress by {pct}% compared to spaced meetings ({avg_clustered:.0f} vs {avg_isolated:.0f})',
                    'detail': f'Based on {len(clustered_stress)} clustered vs {len(isolated_stress)} isolated meeting readings',
                    'tier': 'eureka',
                })

        return patterns
