"""
Template-powered insight engine
Generates contextual insights, canopy scores, compass, and time capsules
"""
import time
import math
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta


class InsightEngine:
    def __init__(self):
        self._cache = None
        self._cache_time = 0
        self._cache_ttl = 60  # 60 second cache

    async def generate_insight(self, readings: List[Dict], summary: Optional[Dict], status: Dict) -> Dict[str, Any]:
        """
        Generate contextual insight from user's current data.
        Returns: {"success": bool, "insight": str}
        """
        # Check cache
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return {"success": True, "insight": self._cache, "cached": True}

        insight = self._build_insight_from_data(readings, summary, status)
        self._cache = insight
        self._cache_time = now
        return {"success": True, "insight": insight, "cached": False}

    def _build_insight_from_data(self, readings: List[Dict], summary: Optional[Dict], status: Dict) -> str:
        """Build a contextual insight from the user's current data using templates."""
        import random

        zone = "steady"
        wellbeing = 50
        stress = 50
        activation = 50

        if readings and len(readings) > 0:
            latest = readings[0]
            zone = latest.get('zone', 'steady')
            wellbeing = latest.get('wellbeing_score', latest.get('mood_score', 50))
            stress = latest.get('stress_score', 50)
            activation = latest.get('activation_score', latest.get('energy_score', 50))

        reading_count = len(readings) if readings else 0
        calm_time = summary.get('time_in_calm_min', 0) if summary else 0
        stressed_time = summary.get('time_in_stressed_min', 0) if summary else 0

        hour = datetime.now().hour
        time_context = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

        if reading_count == 0:
            return "No readings yet today. Start speaking naturally and Attune will begin tracking."

        # Zone-based observation
        zone_msgs = {
            "calm": f"You're currently in the calm zone — stress at {stress:.0f}. A good place to be.",
            "steady": f"You're in a steady state right now — stress at {stress:.0f}, activation at {activation:.0f}.",
            "tense": f"Your voice is showing some tension — stress at {stress:.0f}. A short break could help.",
            "stressed": f"Stress is elevated at {stress:.0f}. Consider stepping away for a moment.",
        }
        observation = zone_msgs.get(zone, zone_msgs["steady"])

        # Time-aware tip
        if time_context == "morning" and stress < 40:
            tip = "Great start to the day — try to maintain this baseline through your first meetings."
        elif time_context == "morning" and stress >= 40:
            tip = "Stress is building early. A 2-minute breathing exercise could reset your baseline."
        elif time_context == "afternoon" and calm_time >= 20:
            tip = f"You've banked {round(calm_time)} minutes of calm time so far — solid recovery."
        elif time_context == "afternoon" and stressed_time > calm_time:
            tip = "The afternoon has been tense. A short walk or change of scenery can help."
        elif time_context == "evening":
            tip = "The workday is winding down. Let yourself transition out of work mode."
        else:
            tips = [
                "Try to notice what activities shift you toward calm.",
                f"With {reading_count} readings today, your patterns are becoming clearer.",
            ]
            tip = random.choice(tips)

        return f"{observation} {tip}"

    async def generate_morning_briefing(self, yesterday_date: str, readings: List[Dict], summary: Optional[Dict]) -> Dict[str, Any]:
        """
        Generate a structured morning briefing from yesterday's data.
        Returns a rich dict with structured morning briefing data.
        """
        if not summary or not readings:
            return {"has_data": False, "date": yesterday_date, "message": "No data from yesterday to review."}

        # --- Extract metrics ---
        avg_stress = summary.get('avg_stress', 50) or 0
        avg_wellbeing = summary.get('avg_wellbeing', summary.get('avg_mood', 50)) or 0
        avg_activation = summary.get('avg_activation', summary.get('avg_energy', 50)) or 0
        avg_calm = summary.get('avg_calm', 50) or 0
        peak_stress = summary.get('peak_stress', 0) or 0
        avg_depression_risk = summary.get('avg_depression_risk', 0) or 0
        avg_anxiety_risk = summary.get('avg_anxiety_risk', 0) or 0
        avg_emotional_stability = summary.get('avg_emotional_stability', 75) or 75

        calm_min = summary.get('time_in_calm_min', 0) or 0
        steady_min = summary.get('time_in_steady_min', 0) or 0
        tense_min = summary.get('time_in_tense_min', 0) or 0
        stressed_min = summary.get('time_in_stressed_min', 0) or 0
        total_speech_min = summary.get('total_speech_min', 0) or 0
        total_meetings = summary.get('total_meetings', 0) or 0

        # --- Overall mental health score (0-100) — aligned with Canopy formula ---
        score = self._compute_canopy_components(summary)

        if score >= 85:
            score_label = "Optimal"
        elif score >= 70:
            score_label = "Good"
        elif score >= 55:
            score_label = "Fair"
        else:
            score_label = "Needs Attention"

        # --- Interpretation helpers ---
        def interp_stress(v):
            if v < 25: return "Low"
            if v < 50: return "Moderate"
            if v < 75: return "High"
            return "Very High"

        def interp_positive(v):
            if v >= 80: return "Excellent"
            if v >= 60: return "Good"
            if v >= 40: return "Moderate"
            return "Low"

        def interp_depression(v):
            # v is now on 0-100 scale (mapped from PHQ-9 cutoffs 5/10/15 out of 27)
            if v < 19: return "Minimal"
            if v < 37: return "Mild"
            if v < 56: return "Moderate"
            return "Severe"

        def interp_anxiety(v):
            # v is now on 0-100 scale (mapped from GAD-7 cutoffs 5/8/11 out of 21)
            if v < 24: return "Minimal"
            if v < 38: return "Mild"
            if v < 52: return "Moderate"
            return "Severe"

        # --- Metrics dict ---
        metrics = {
            "avg_stress":       {"value": round(avg_stress, 1),       "max": 100, "label": "Avg Stress",       "interpretation": interp_stress(avg_stress)},
            "avg_wellbeing":    {"value": round(avg_wellbeing, 1),    "max": 100, "label": "Avg Wellbeing",    "interpretation": interp_positive(avg_wellbeing)},
            "avg_activation":   {"value": round(avg_activation, 1),   "max": 100, "label": "Avg Activation",   "interpretation": interp_positive(avg_activation)},
            "avg_calm":         {"value": round(avg_calm, 1),         "max": 100, "label": "Avg Calm",         "interpretation": interp_positive(avg_calm)},
            "peak_stress":      {"value": round(peak_stress, 1),      "max": 100, "label": "Peak Stress",      "interpretation": interp_stress(peak_stress)},
            "avg_depression_risk": {"value": round(avg_depression_risk, 1), "max": 100, "label": "Depression Risk", "interpretation": interp_depression(avg_depression_risk)},
            "avg_anxiety_risk":    {"value": round(avg_anxiety_risk, 1),    "max": 100, "label": "Anxiety Risk",    "interpretation": interp_anxiety(avg_anxiety_risk)},
            "avg_emotional_stability": {"value": round(avg_emotional_stability, 1), "max": 100, "label": "Stability", "interpretation": interp_positive(avg_emotional_stability)},
        }

        # --- Zone breakdown ---
        total_zone_min = calm_min + steady_min + tense_min + stressed_min
        def zone_pct(v):
            return round(v / total_zone_min * 100, 1) if total_zone_min > 0 else 0

        zones = {
            "calm":     {"minutes": round(calm_min),     "pct": zone_pct(calm_min)},
            "steady":   {"minutes": round(steady_min),   "pct": zone_pct(steady_min)},
            "tense":    {"minutes": round(tense_min),    "pct": zone_pct(tense_min)},
            "stressed": {"minutes": round(stressed_min), "pct": zone_pct(stressed_min)},
        }

        # --- Activity stats ---
        total_readings = len(readings)
        timestamps = sorted([r['timestamp'] for r in readings if r.get('timestamp')])
        if timestamps:
            first_dt = datetime.fromisoformat(timestamps[0])
            last_dt = datetime.fromisoformat(timestamps[-1])
            first_reading = first_dt.strftime("%-I:%M %p")
            last_reading = last_dt.strftime("%-I:%M %p")
            active_hours = round((last_dt - first_dt).total_seconds() / 3600, 1)
        else:
            first_reading = "--"
            last_reading = "--"
            active_hours = 0

        activity = {
            "total_readings": total_readings,
            "first_reading": first_reading,
            "last_reading": last_reading,
            "active_hours": active_hours,
            "total_speech_min": round(total_speech_min, 1),
            "total_meetings": total_meetings,
        }

        # --- Highlights ---
        highlights = []
        if avg_stress < 25:
            highlights.append(f"Stress stayed low all day (avg {avg_stress:.0f}/100).")
        elif avg_stress > 60:
            highlights.append(f"Stress was elevated (avg {avg_stress:.0f}/100). Consider extra recovery today.")
        if calm_min > 60:
            highlights.append(f"You spent {round(calm_min)} min in the calm zone — great regulation.")
        if stressed_min > 30:
            highlights.append(f"You had {round(stressed_min)} min in the stressed zone. Watch for early signs today.")
        if avg_wellbeing >= 80:
            highlights.append(f"Wellbeing was excellent ({avg_wellbeing:.0f}/100).")
        elif avg_wellbeing < 40:
            highlights.append(f"Wellbeing was lower than usual ({avg_wellbeing:.0f}/100). A good morning routine may help.")
        if peak_stress > 60:
            highlights.append(f"Peak stress hit {peak_stress:.0f}. Planning breaks around intense tasks may help.")
        if total_speech_min > 30:
            highlights.append(f"You spoke for {total_speech_min:.0f} min — a talkative day.")
        # Cap at 5
        highlights = highlights[:5]
        if not highlights:
            highlights.append(f"Overall score: {score}/100 ({score_label}). A balanced day.")

        # --- Coach's note ---
        coach_note = self._get_coach_note(score, score_label, avg_stress, avg_wellbeing, avg_activation, calm_min, peak_stress)

        return {
            "has_data": True,
            "overall_score": score,
            "score_label": score_label,
            "date": yesterday_date,
            "metrics": metrics,
            "zones": zones,
            "activity": activity,
            "highlights": highlights,
            "coach_note": coach_note,
        }

    def _get_coach_note(self, score, label, stress, wellbeing, activation, calm_min, peak_stress) -> str:
        """Generate a data-specific coach note from modular templates."""
        import random
        parts = []

        # --- Part 1: Yesterday summary (based on overall score) ---
        if score >= 80:
            openers = [
                "Yesterday was a strong day for your wellbeing.",
                "Your voice showed excellent balance yesterday.",
                "A really solid day — your metrics were well above average.",
            ]
        elif score >= 65:
            openers = [
                "Yesterday was a good day overall.",
                "Your voice showed steady composure throughout the day.",
                "A balanced day — your body handled it well.",
            ]
        elif score >= 50:
            openers = [
                "Yesterday had its ups and downs.",
                "A mixed day — some tension, but you managed.",
                "Your voice showed some strain yesterday, but you recovered.",
            ]
        else:
            openers = [
                "Yesterday was a tougher day.",
                "Your voice carried more tension than usual yesterday.",
                "A demanding day — your metrics reflected the load.",
            ]
        parts.append(random.choice(openers))

        # --- Part 2: One data-specific observation ---
        observations = []
        if calm_min >= 60:
            observations.append(f"You spent {round(calm_min)} minutes in the calm zone — great self-regulation.")
        elif calm_min >= 30:
            observations.append(f"You logged {round(calm_min)} minutes of calm time, which helped offset the busier moments.")
        elif calm_min > 0:
            observations.append(f"Calm time was only {round(calm_min)} minutes — building in short breaks could help today.")

        if peak_stress >= 75:
            observations.append(f"Peak stress hit {peak_stress:.0f} — planning buffer time around intense blocks may help.")
        elif peak_stress >= 50:
            observations.append(f"Stress peaked at {peak_stress:.0f}, which is manageable but worth watching.")

        if wellbeing >= 80:
            observations.append(f"Wellbeing was excellent at {wellbeing:.0f} — that positive momentum can carry into today.")
        elif wellbeing < 40:
            observations.append(f"Wellbeing dipped to {wellbeing:.0f} — a good morning routine can help reset your baseline.")

        if activation < 35:
            observations.append("Activation was running low — prioritize sleep and hydration today.")
        elif activation >= 75:
            observations.append(f"Activation was solid at {activation:.0f} — a good sign for tackling today's priorities.")

        if stress >= 60 and calm_min >= 30:
            observations.append(f"Despite average stress of {stress:.0f}, you still found {round(calm_min)} minutes of calm — that recovery matters.")

        if observations:
            parts.append(random.choice(observations))

        # --- Part 3: Forward-looking intention ---
        intentions = [
            "Today, try to notice your first signs of tension and respond with a brief pause.",
            "Set an intention to take short breaks between tasks today.",
            "Consider front-loading deep work before your busiest meetings today.",
            "Today, try one micro-recovery: a short walk, a stretch, or 60 seconds of slow breathing.",
            "Pay attention to which tasks energize you vs. drain you today.",
        ]
        if stress >= 60:
            intentions.extend([
                "Start today with something grounding — even a few slow breaths can shift your baseline.",
                "Block 10 minutes of buffer time between your most intense meetings today.",
            ])
        if calm_min < 20:
            intentions.extend([
                "Aim for at least 15 minutes of calm time today — small pockets add up.",
                "Try stepping away from your screen for a few minutes between meetings.",
            ])
        if activation < 40:
            intentions.extend([
                "Protect your energy today — say no to one non-essential task.",
                "A short walk outside can do more for low activation than another coffee.",
            ])
        parts.append(random.choice(intentions))

        return " ".join(parts)

    # ============ Canopy Score (Feature #1) ============

    def _compute_canopy_components(self, s: Dict) -> float:
        """
        Shared Canopy Score formula: 7 voice scores + recovery, weighted by validity.
        Missing new scores (depression_risk, anxiety_risk, emotional_stability) get their
        weight redistributed proportionally to the remaining components.
        Returns score in [0, 100].
        """
        # Define components: (key, weight, inverted?)
        components = [
            ('stress',              0.15, True),
            ('wellbeing',           0.13, False),
            ('depression_risk',     0.13, True),
            ('activation',          0.13, False),
            ('calm',                0.12, False),
            ('anxiety_risk',        0.12, True),
            ('emotional_stability', 0.12, False),
        ]

        # Extract raw values (None = missing)
        # Use `or` for fallbacks so 0/None values fall through to legacy keys
        raw = {}
        raw['stress'] = s.get('avg_stress')
        raw['wellbeing'] = s.get('avg_wellbeing') or s.get('avg_mood')
        raw['activation'] = s.get('avg_activation') or s.get('avg_energy')
        raw['calm'] = s.get('avg_calm')
        raw['depression_risk'] = s.get('avg_depression_risk')
        raw['anxiety_risk'] = s.get('avg_anxiety_risk')
        raw['emotional_stability'] = s.get('avg_emotional_stability')

        # Recovery: calm-time ratio (always available from zone minutes)
        calm_min = s.get('time_in_calm_min', 0) or 0
        total_min = (calm_min
                     + (s.get('time_in_steady_min', 0) or 0)
                     + (s.get('time_in_tense_min', 0) or 0)
                     + (s.get('time_in_stressed_min', 0) or 0))
        recovery = (calm_min / total_min * 100) if total_min > 0 else 50
        recovery_weight = 0.10

        # Determine which voice components are present
        present = []
        missing_weight = 0.0
        for key, weight, inverted in components:
            val = raw[key]
            if val is not None:
                present.append((key, weight, inverted))
            else:
                missing_weight += weight

        # Redistribute missing weight proportionally
        total_present_weight = sum(w for _, w, _ in present)
        if total_present_weight <= 0:
            # No voice scores at all — return recovery only, scaled to 100
            return max(0, min(100, round(recovery)))

        redistribution_factor = (total_present_weight + missing_weight) / total_present_weight

        # Compute weighted sum
        score = 0.0
        for key, weight, inverted in present:
            val = min(100, max(0, raw[key] or 0))
            if inverted:
                val = 100 - val
            score += weight * redistribution_factor * val

        # Add recovery
        score += recovery_weight * recovery

        # Oura-style normalization: power curve maps raw average (~59) → ~75
        # so a typical healthy user on a typical day lands in the "Good" zone.
        # Bounds 0 and 100 are preserved. Great/terrible days compress naturally.
        score = max(0, min(100, score))
        score = round(100 * (score / 100) ** 0.55)

        return score

    def compute_canopy_score(self, db, yesterday_summary: Dict) -> Dict[str, Any]:
        """Compute today's Canopy Score from yesterday's data with fixed daily wellness weights."""
        if not yesterday_summary:
            return {'score': 0, 'has_data': False}

        today = date.today()
        dow = today.weekday()  # 0=Monday

        # Fixed weights — daily resilience + recovery score
        profile_name = 'Daily Wellness'

        score = self._compute_canopy_components(yesterday_summary)

        # Store in DB
        db.set_canopy_score(today.isoformat(), score, dow, profile_name)

        return {
            'score': score,
            'has_data': True,
            'date': today.isoformat(),
            'profile': profile_name,
            'day_of_week': dow,
        }

    def compute_intraday_canopy_score(self, db) -> Dict[str, Any]:
        """Compute today's live intraday Canopy Score. Requires 1+ reading today."""
        readings = db.get_today_readings()
        reading_count = len(readings)

        if reading_count < 1:
            return {
                'has_data': False,
                'reading_count': reading_count,
                'readings_needed': 1 - reading_count,
            }

        today_summary = db.compute_daily_summary()
        if not today_summary:
            return {'has_data': False, 'reading_count': reading_count, 'readings_needed': 0}

        score = self._compute_canopy_components(today_summary)

        return {
            'score': score,
            'has_data': True,
            'reading_count': reading_count,
            'readings_needed': 0,
            'profile': "Today's Wellness",
            'date': date.today().isoformat(),
        }

    # ============ Compass (Feature #7) ============

    def compute_compass(self, db) -> Dict[str, Any]:
        """Compute weekly direction arrow and biggest changes."""
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()

        # Check if already computed this week
        existing = db.get_compass_entry(week_start)
        if existing:
            return existing

        # Get this week vs last week
        summaries = db.get_daily_summaries(days=21)
        if len(summaries) < 7:
            return {'direction': 'holding', 'has_data': False}

        sorted_s = sorted(summaries, key=lambda s: s['date'], reverse=True)

        this_week = sorted_s[:7]
        last_week = sorted_s[7:14] if len(sorted_s) >= 14 else sorted_s[7:]

        if not last_week:
            return {'direction': 'holding', 'has_data': False}

        # Compare metrics
        metrics = ['avg_stress', 'avg_wellbeing', 'avg_activation', 'avg_calm']
        labels = {'avg_stress': 'stress', 'avg_wellbeing': 'wellbeing', 'avg_activation': 'activation', 'avg_calm': 'calmness'}

        changes = {}
        for m in metrics:
            tw = sum(s.get(m, 50) for s in this_week) / len(this_week)
            lw = sum(s.get(m, 50) for s in last_week) / len(last_week)
            changes[m] = tw - lw

        # Overall direction based on weighted composite
        composite = (
            -changes.get('avg_stress', 0) * 0.3 +  # Less stress = positive
            changes.get('avg_wellbeing', 0) * 0.3 +
            changes.get('avg_activation', 0) * 0.2 +
            changes.get('avg_calm', 0) * 0.2
        )

        if composite > 3:
            direction = 'ascending'
        elif composite < -3:
            direction = 'descending'
        else:
            direction = 'holding'

        # Find biggest positive and negative changes
        positive_changes = {m: c for m, c in changes.items() if
                          (c < 0 and m == 'avg_stress') or (c > 0 and m != 'avg_stress')}
        negative_changes = {m: c for m, c in changes.items() if
                          (c > 0 and m == 'avg_stress') or (c < 0 and m != 'avg_stress')}

        biggest_positive = ''
        if positive_changes:
            best_m = max(positive_changes, key=lambda k: abs(positive_changes[k]))
            biggest_positive = f"{labels[best_m]} improved by {abs(changes[best_m]):.0f} points"

        biggest_negative = ''
        if negative_changes:
            worst_m = max(negative_changes, key=lambda k: abs(negative_changes[k]))
            biggest_negative = f"{labels[worst_m]} shifted by {abs(changes[worst_m]):.0f} points"

        db.upsert_compass(week_start, direction, biggest_positive, biggest_negative)

        return {
            'week_start': week_start,
            'direction': direction,
            'biggest_positive': biggest_positive,
            'biggest_negative': biggest_negative,
            'intention': None,
            'has_data': True,
        }

    # ============ Time Capsule (Feature #9) ============

    def check_time_capsules(self, db) -> List[Dict[str, Any]]:
        """Generate time capsule messages at meaningful intervals."""
        capsules = []
        all_readings = db.get_readings(limit=10000)
        all_summaries = db.get_daily_summaries(days=365)

        if not all_readings:
            return capsules

        total_readings = len(all_readings)
        total_days = len(all_summaries)

        # Day 8: "One week ago, your first reading"
        if total_days >= 8:
            first_date = all_summaries[-1]['date'] if all_summaries else None
            if first_date:
                capsules.append({
                    'trigger_type': 'week_1',
                    'message': f'One week ago ({first_date}), your journey with Attune began.',
                })

        # Day 15: Compare stress now vs then
        if total_days >= 15:
            sorted_s = sorted(all_summaries, key=lambda s: s['date'])
            first_week_stress = sum(s.get('avg_stress', 50) for s in sorted_s[:7]) / 7
            last_week_stress = sum(s.get('avg_stress', 50) for s in sorted_s[-7:]) / 7
            diff = first_week_stress - last_week_stress
            if diff > 0:
                capsules.append({
                    'trigger_type': 'week_2_compare',
                    'message': f'Two weeks ago your stress was {first_week_stress:.0f} — today it\'s {last_week_stress:.0f}. That\'s {diff:.0f} points of progress.',
                })
            else:
                capsules.append({
                    'trigger_type': 'week_2_compare',
                    'message': f'Two weeks in. Your stress went from {first_week_stress:.0f} to {last_week_stress:.0f}. Awareness is the first step.',
                })

        # Day 31: Month in review
        if total_days >= 31:
            sorted_s = sorted(all_summaries, key=lambda s: s['date'])
            week1_wellbeing = sum(s.get('avg_wellbeing', s.get('avg_mood', 50)) for s in sorted_s[:7]) / 7
            week4_wellbeing = sum(s.get('avg_wellbeing', s.get('avg_mood', 50)) for s in sorted_s[-7:]) / 7
            capsules.append({
                'trigger_type': 'month_review',
                'message': f'One month with Attune! Week 1 wellbeing: {week1_wellbeing:.0f} → Week 4 wellbeing: {week4_wellbeing:.0f}. {total_readings} readings captured.',
            })

        # Hours-spoken milestones (logarithmic spacing)
        total_hours = sum(r.get('speech_duration_sec', 0) for r in all_readings) / 3600
        for milestone_hrs in [1, 5, 10, 20, 50, 100, 200, 500]:
            if total_hours >= milestone_hrs:
                capsules.append({
                    'trigger_type': f'hours_{milestone_hrs}',
                    'message': f"You've spoken for {milestone_hrs} {'hour' if milestone_hrs == 1 else 'hours'} while Attune listened.",
                })

        # Store new capsules (duplicates silently skipped via UNIQUE constraint)
        for c in capsules:
            db.add_time_capsule(c['trigger_type'], c['message'], c.get('detail'))

        return db.get_time_capsules(limit=5)

    # ============ Weekly Wrapped (Your Week in Voice) ============

    def generate_weekly_wrapped(self, db) -> Dict[str, Any]:
        """
        Generate a weekly summary card: last 7 days vs prior 7 days.
        Returns structured data for frontend rendering.
        """
        summaries = db.get_daily_summaries(days=21)
        if len(summaries) < 7:
            return {'has_data': False, 'message': 'Need at least 7 days of data for weekly wrap.'}

        sorted_s = sorted(summaries, key=lambda s: s['date'], reverse=True)
        this_week = sorted_s[:7]
        prev_week = sorted_s[7:14] if len(sorted_s) >= 14 else []

        # Metrics for this week
        tw_stress = sum(s.get('avg_stress', 50) or 50 for s in this_week) / len(this_week)
        tw_wellbeing = sum(s.get('avg_wellbeing', s.get('avg_mood', 50)) or 50 for s in this_week) / len(this_week)
        tw_activation = sum(s.get('avg_activation', s.get('avg_energy', 50)) or 50 for s in this_week) / len(this_week)
        tw_calm = sum(s.get('avg_calm', 50) or 50 for s in this_week) / len(this_week)

        # Canopy scores
        canopy_scores = []
        for s in this_week:
            cs = db.get_canopy_score(s['date'])
            canopy_scores.append(cs['score'] if cs else 0)
        avg_canopy = sum(canopy_scores) / len(canopy_scores) if canopy_scores else 0

        # Previous week canopy for trend
        prev_canopy = 0
        if prev_week:
            prev_scores = []
            for s in prev_week:
                cs = db.get_canopy_score(s['date'])
                prev_scores.append(cs['score'] if cs else 0)
            prev_canopy = sum(prev_scores) / len(prev_scores) if prev_scores else 0

        canopy_trend = avg_canopy - prev_canopy

        # Best and worst days
        best_day = min(this_week, key=lambda s: s.get('avg_stress', 50) or 50)
        worst_day = max(this_week, key=lambda s: s.get('avg_stress', 50) or 50)
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

        def day_label(d_str):
            try:
                from datetime import date as dt_date
                d = dt_date.fromisoformat(d_str)
                return day_names[d.weekday()]
            except (ValueError, AttributeError):
                return d_str

        # Zone distribution
        total_calm = sum(s.get('time_in_calm_min', 0) or 0 for s in this_week)
        total_steady = sum(s.get('time_in_steady_min', 0) or 0 for s in this_week)
        total_tense = sum(s.get('time_in_tense_min', 0) or 0 for s in this_week)
        total_stressed = sum(s.get('time_in_stressed_min', 0) or 0 for s in this_week)
        total_zone = total_calm + total_steady + total_tense + total_stressed

        def zone_pct(v):
            return round(v / total_zone * 100, 1) if total_zone > 0 else 0

        # Rings completion rate
        all_readings = []
        for s in this_week:
            d = date.fromisoformat(s['date'])
            day_readings = db.get_readings_for_date(d)
            all_readings.append(len(day_readings))

        # Approximate rings closure: days with 5+ readings AND 30+ min calm
        rings_closed_days = sum(
            1 for s in this_week
            if (s.get('time_in_calm_min', 0) or 0) >= 10
            and len(db.get_readings_for_date(date.fromisoformat(s['date']))) >= 3
        )

        # Top echo of the week
        echoes = db.get_echoes(limit=5)
        top_echo = echoes[0]['message'] if echoes else None

        # Compass direction
        compass = self.compute_compass(db)
        direction = compass.get('direction', 'holding')

        # One-line summary
        if tw_stress < 30:
            summary_line = "A calm, collected week. You're in a great rhythm."
        elif tw_stress < 50:
            summary_line = "A steady week with manageable stress levels."
        elif tw_stress < 65:
            summary_line = "A busy week. Your voice showed some strain."
        else:
            summary_line = "A demanding week. Consider prioritizing recovery."

        # Week-over-week changes
        wow = {}
        if prev_week:
            pw_stress = sum(s.get('avg_stress', 50) or 50 for s in prev_week) / len(prev_week)
            wow['stress'] = round(tw_stress - pw_stress, 1)
            pw_wellbeing = sum(s.get('avg_wellbeing', s.get('avg_mood', 50)) or 50 for s in prev_week) / len(prev_week)
            wow['wellbeing'] = round(tw_wellbeing - pw_wellbeing, 1)

        return {
            'has_data': True,
            'week_ending': this_week[0]['date'],
            'canopy': {
                'avg': round(avg_canopy),
                'trend': round(canopy_trend, 1),
                'daily': canopy_scores,
            },
            'metrics': {
                'avg_stress': round(tw_stress, 1),
                'avg_wellbeing': round(tw_wellbeing, 1),
                'avg_activation': round(tw_activation, 1),
                'avg_calm': round(tw_calm, 1),
            },
            'best_day': {
                'date': best_day['date'],
                'label': day_label(best_day['date']),
                'stress': round(best_day.get('avg_stress', 50) or 50),
            },
            'worst_day': {
                'date': worst_day['date'],
                'label': day_label(worst_day['date']),
                'stress': round(worst_day.get('avg_stress', 50) or 50),
            },
            'zones': {
                'calm': {'min': round(total_calm), 'pct': zone_pct(total_calm)},
                'steady': {'min': round(total_steady), 'pct': zone_pct(total_steady)},
                'tense': {'min': round(total_tense), 'pct': zone_pct(total_tense)},
                'stressed': {'min': round(total_stressed), 'pct': zone_pct(total_stressed)},
            },
            'rings_closed': rings_closed_days,
            'top_echo': top_echo,
            'compass_direction': direction,
            'summary_line': summary_line,
            'week_over_week': wow,
        }

    # ============ First Spark — Interpret First Reading ============

    def interpret_first_reading(self, reading: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate narrative interpretation for a user's first reading.
        Returns text + population percentile.
        """
        stress = reading.get('stress_score', 50) or 50
        wellbeing = reading.get('wellbeing_score', reading.get('mood_score', 50)) or 50
        activation = reading.get('activation_score', reading.get('energy_score', 50)) or 50
        calm = reading.get('calm_score', 50) or 50

        # Determine overall tone
        if stress < 30:
            stress_desc = "low"
        elif stress < 50:
            stress_desc = "moderate"
        elif stress < 70:
            stress_desc = "elevated"
        else:
            stress_desc = "high"

        if activation > 60:
            activation_desc = "good"
        elif activation > 40:
            activation_desc = "moderate"
        else:
            activation_desc = "low"

        narrative = (
            f"Your voice shows {stress_desc} stress and {activation_desc} activation. "
            f"We've begun building your personal baseline. "
            f"After 3 more readings, we'll show how your voice compares to your own normal. "
            f"After 7 days, we'll start discovering patterns unique to you."
        )

        # Population percentile (based on calibration norms — hardcoded distribution)
        # Mean stress ~42, std ~15 from calibration data
        pop_mean = 42.0
        pop_std = 15.0
        if pop_std > 0:
            z = (stress - pop_mean) / pop_std
            # Approximate CDF using logistic approximation
            cdf = 1.0 / (1.0 + math.exp(-1.7 * z))
            percentile = round((1 - cdf) * 100)
        else:
            percentile = 50

        # Progressive unlock preview
        unlocks = [
            {'day': 3, 'label': 'Personalized Scores', 'desc': 'Calibrated to your voice'},
            {'day': 7, 'label': 'First Patterns', 'desc': 'Day-of-week & time-of-day insights'},
            {'day': 14, 'label': 'Deep Insights', 'desc': 'Recovery patterns & trend analysis'},
            {'day': 30, 'label': 'Monthly Trajectory', 'desc': 'Long-term trends & stability patterns'},
        ]

        return {
            'narrative': narrative,
            'stress_percentile': percentile,
            'percentile_text': f"Your stress is lower than {percentile}% of first-time readings",
            'unlocks': unlocks,
        }

    async def generate_evening_recap(self, today_summary: Dict, today_readings: List[Dict]) -> str:
        """Generate evening recap based on today's data using templates."""
        if not today_summary or not today_readings:
            return "Your day is just beginning. Check back this evening for a recap."

        import random

        avg_stress = today_summary.get('avg_stress', 50)
        peak_stress = today_summary.get('peak_stress', 0)
        calm_time = today_summary.get('time_in_calm_min', 0)
        stressed_time = today_summary.get('time_in_stressed_min', 0)
        meetings = today_summary.get('total_meetings', 0)

        # Find peak stress time
        peak_time = ""
        if today_readings:
            peak_reading = max(today_readings, key=lambda r: r.get('stress_score', 0))
            peak_timestamp = datetime.fromisoformat(peak_reading['timestamp'])
            peak_time = peak_timestamp.strftime("%-I:%M %p")

        # Build recap from parts
        parts = []

        # Part 1: Day arc
        if avg_stress < 30:
            parts.append("A calm day — your voice stayed relaxed throughout.")
        elif avg_stress < 50:
            parts.append(f"A steady day with manageable stress (avg {avg_stress:.0f}).")
        elif avg_stress < 70:
            parts.append(f"A busy day — stress averaged {avg_stress:.0f} with a peak{f' around {peak_time}' if peak_time else ''} at {peak_stress:.0f}.")
        else:
            parts.append(f"A demanding day — stress hit {peak_stress:.0f}{f' around {peak_time}' if peak_time else ''}.")

        # Part 2: Highlight
        if calm_time >= 45:
            parts.append(f"You found {round(calm_time)} minutes of calm time — that's strong recovery.")
        elif calm_time >= 15:
            parts.append(f"You managed {round(calm_time)} minutes of calm despite the pace.")
        elif stressed_time > 30:
            parts.append(f"You spent {round(stressed_time)} minutes in the stressed zone — recovery tonight is key.")
        elif meetings > 3:
            parts.append(f"With {meetings} meetings, it was a talk-heavy day.")

        # Part 3: Recovery tip
        tips = [
            "Wind down with something non-screen tonight.",
            "Rest well — tomorrow is a fresh start.",
            "A good night's sleep is the best recovery tool.",
            "Try to disconnect from work for the rest of the evening.",
        ]
        if avg_stress >= 60:
            tips.extend([
                "Give yourself permission to do nothing tonight.",
                "A short walk or gentle stretch can help release the day's tension.",
            ])
        parts.append(random.choice(tips))

        return " ".join(parts)

    # ================================================================
    #  Evening Summary (extracted from /api/evening-summary endpoint)
    # ================================================================

    def compute_evening_summary(self, db):
        """
        Compute the evening summary data structure (sync portion).
        Canopy score must be resolved async by the caller.

        Returns:
            dict with evening summary fields, or empty dict if no data.
        """
        from api.constants import ZONE_ORDER

        today_readings = db.get_today_readings()
        if not today_readings:
            return None

        yesterday = date.today() - timedelta(days=1)
        today_summary = db.compute_daily_summary()

        # Compact timeline (stress per 30-min bucket, 6 AM - 8 PM)
        buckets = {}
        for r in today_readings:
            try:
                ts = datetime.fromisoformat(r.get('timestamp', ''))
                hour_bucket = ts.hour + (0.5 if ts.minute >= 30 else 0)
                if 6 <= hour_bucket < 20:
                    if hour_bucket not in buckets:
                        buckets[hour_bucket] = []
                    buckets[hour_bucket].append({
                        'stress': r.get('stress_score', 50) or 50,
                        'zone': r.get('zone', 'steady') or 'steady'
                    })
            except (ValueError, TypeError, KeyError):
                continue
        timeline = [
            {
                'hour': h,
                'stress': round(sum(v['stress'] for v in vs) / len(vs)),
                'zone': max(set(v['zone'] for v in vs),
                            key=lambda z: ZONE_ORDER.index(z) if z in ZONE_ORDER else 0)
            }
            for h, vs in sorted(buckets.items())
        ]

        # Peak stress hour
        peak_hour = None
        peak_stress = 0
        for r in today_readings:
            s = r.get('stress_score', 0) or 0
            if s > peak_stress:
                peak_stress = s
                try:
                    ts = datetime.fromisoformat(r.get('timestamp', ''))
                    peak_hour = ts.strftime('%-I %p')
                except (ValueError, TypeError, KeyError):
                    peak_hour = None

        # Calm peak hour
        hourly_stress = {}
        for r in today_readings:
            try:
                ts = datetime.fromisoformat(r.get('timestamp', ''))
                h = ts.hour
                if h not in hourly_stress:
                    hourly_stress[h] = []
                hourly_stress[h].append(r.get('stress_score', 50) or 50)
            except (ValueError, TypeError, KeyError):
                continue
        calm_hour = None
        if hourly_stress:
            best_h = min(hourly_stress, key=lambda h: sum(hourly_stress[h]) / len(hourly_stress[h]))
            calm_hour = f"{best_h % 12 or 12}\u2013{(best_h + 1) % 12 or 12} {'AM' if best_h < 12 else 'PM'}"

        # Comparison deltas
        yesterday_summary = db.get_summary_for_date(yesterday)
        canopy_yesterday = db.get_canopy_score(yesterday.isoformat())

        stress_delta = None
        if today_summary and yesterday_summary:
            today_stress = today_summary.get('avg_stress') or 0
            yest_stress = yesterday_summary.get('avg_stress') or 0
            if today_stress and yest_stress:
                stress_delta = round(today_stress - yest_stress)

        # Insight line
        insight = None
        if calm_hour and peak_hour:
            insight = f"Your calmest hour was {calm_hour}. Stress peaked around {peak_hour}."
        elif calm_hour:
            insight = f"Your calmest period was {calm_hour}."
        elif today_summary:
            calm_min = today_summary.get('time_in_calm_min', 0) or 0
            if calm_min >= 60:
                insight = f"You spent {round(calm_min / 60, 1)} hours in a calm state today."

        return {
            'has_data': True,
            'canopy_yesterday': canopy_yesterday,
            'avg_stress': round(today_summary.get('avg_stress') or 0) if today_summary else None,
            'stress_delta': stress_delta,
            'time_in_calm_min': round(today_summary.get('time_in_calm_min') or 0) if today_summary else 0,
            'total_speech_min': round(today_summary.get('total_speech_min') or 0) if today_summary else 0,
            'reading_count': len(today_readings),
            'peak_stress_hour': peak_hour,
            'calm_peak_hour': calm_hour,
            'timeline': timeline,
            'insight': insight,
        }
