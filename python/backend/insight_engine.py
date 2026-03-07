"""
LLM-enhanced insight engine
Generates contextual insights, wellness scores, and compass.
Uses Ollama (local LLM) for text generation with template fallback.
"""
import time
import math
import re
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta

logger = logging.getLogger('lucid.insight_engine')


class InsightEngine:
    def __init__(self, ollama_enabled=True, ollama_host="http://localhost:11434",
                 ollama_model="phi4-mini", ollama_timeout_sec=10.0):
        self._cache = None
        self._cache_time = 0
        self._cache_ttl = 60  # 60 second cache
        self._ollama_enabled = ollama_enabled
        self._ollama_host = ollama_host.rstrip('/')
        self._ollama_model = ollama_model
        self._ollama_timeout = ollama_timeout_sec
        self._ollama_available = None  # None=unchecked, True/False after check
        self._ollama_client = None     # Lazy httpx.AsyncClient
        logger.info(f"Insight engine ready (Ollama: {'enabled' if ollama_enabled else 'disabled'}, model: {ollama_model})")

    # ============ Ollama LLM Helpers ============

    async def _get_ollama_client(self):
        """Lazy-init httpx.AsyncClient."""
        if self._ollama_client is None:
            import httpx
            self._ollama_client = httpx.AsyncClient(timeout=self._ollama_timeout)
        return self._ollama_client

    async def _check_ollama_available(self) -> bool:
        """Check if Ollama is reachable. Caches result; re-checks on failure."""
        if self._ollama_available is True:
            return True
        # Re-check if previously failed or unchecked
        try:
            client = await self._get_ollama_client()
            resp = await client.get(f"{self._ollama_host}/api/tags")
            self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    async def _ollama_generate(self, system_prompt: str, user_prompt: str, max_chars: int = 300) -> Optional[str]:
        """Call Ollama /api/generate. Returns cleaned text or None on any failure."""
        if not self._ollama_enabled:
            return None
        if not await self._check_ollama_available():
            return None
        try:
            import httpx
            client = await self._get_ollama_client()
            # Use longer timeout for generate (model cold-start can take 15-30s)
            resp = await client.post(
                f"{self._ollama_host}/api/generate",
                json={
                    "model": self._ollama_model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "options": {"num_predict": max_chars, "temperature": 0.7},
                },
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
            if resp.status_code != 200:
                logger.warning(f"Ollama returned {resp.status_code}")
                return None
            text = resp.json().get("response", "").strip()
            if not text:
                return None
            return self._clean_llm_output(text, max_chars)
        except Exception as e:
            logger.warning(f"Ollama generate failed: {e}")
            self._ollama_available = False
            return None

    @staticmethod
    def _clean_llm_output(text: str, max_chars: int) -> str:
        """Strip markdown artifacts and truncate at sentence boundary."""
        # Remove markdown bold/italic/headers
        text = re.sub(r'[#*_`]+', '', text)
        # Remove any leading/trailing quotes
        text = text.strip().strip('"').strip("'").strip()
        # Truncate at sentence boundary if over limit
        if len(text) > max_chars:
            # Find last sentence end before max_chars
            truncated = text[:max_chars]
            last_period = truncated.rfind('.')
            last_excl = truncated.rfind('!')
            last_q = truncated.rfind('?')
            cut = max(last_period, last_excl, last_q)
            if cut > max_chars // 3:
                text = truncated[:cut + 1]
            else:
                text = truncated.rstrip() + "..."
        return text

    async def generate_insight(self, readings: List[Dict], summary: Optional[Dict], status: Dict) -> Dict[str, Any]:
        """
        Generate contextual insight from user's current data.
        Returns: {"success": bool, "insight": str}
        """
        # Check cache
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return {"success": True, "insight": self._cache, "cached": True}

        # Try LLM first, fall back to templates
        insight = await self._generate_insight_llm(readings, summary, status)
        if not insight:
            insight = self._build_insight_from_data(readings, summary, status)

        self._cache = insight
        self._cache_time = now
        return {"success": True, "insight": insight, "cached": False}

    async def _generate_insight_llm(self, readings: List[Dict], summary: Optional[Dict], status: Dict) -> Optional[str]:
        """Try to generate a live insight via Ollama."""
        reading_count = len(readings) if readings else 0
        if reading_count == 0:
            return None

        latest = readings[0] if readings else {}
        zone = latest.get('zone', 'steady')
        stress = latest.get('stress_score', 50)
        wellbeing = latest.get('wellbeing_score', latest.get('mood_score', 50))
        activation = latest.get('activation_score', latest.get('energy_score', 50))
        calm_time = summary.get('time_in_calm_min', 0) if summary else 0
        stressed_time = summary.get('time_in_stressed_min', 0) if summary else 0
        hour = datetime.now().hour
        time_context = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

        system_prompt = (
            "You are a voice wellness coach inside a desktop app. "
            "Write exactly 2 sentences. No greetings. No questions. "
            "Only reference the data provided. Be warm but concise."
        )
        user_prompt = (
            f"Zone: {zone}. Stress: {stress:.0f}/100. Wellbeing: {wellbeing:.0f}/100. "
            f"Activation: {activation:.0f}/100. Readings today: {reading_count}. "
            f"Calm time: {calm_time:.0f} min. Stressed time: {stressed_time:.0f} min. "
            f"Time of day: {time_context}."
        )
        return await self._ollama_generate(system_prompt, user_prompt, max_chars=250)

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
            return "No readings yet today. Start speaking naturally and Lucid will begin tracking."

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

        # --- Overall mental health score (0-100) — aligned with Wellness formula ---
        score = self._compute_wellness_components(summary)

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
        coach_note = await self._get_coach_note(score, score_label, avg_stress, avg_wellbeing, avg_activation, calm_min, peak_stress)

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

    async def _get_coach_note(self, score, label, stress, wellbeing, activation, calm_min, peak_stress) -> str:
        """Generate a coach note via LLM with template fallback."""
        note = await self._get_coach_note_llm(score, label, stress, wellbeing, activation, calm_min, peak_stress)
        if not note:
            note = self._get_coach_note_template(score, label, stress, wellbeing, activation, calm_min, peak_stress)
        return note

    async def _get_coach_note_llm(self, score, label, stress, wellbeing, activation, calm_min, peak_stress) -> Optional[str]:
        """Try to generate a coach note via Ollama."""
        system_prompt = (
            "You are a voice wellness coach writing a morning briefing note. "
            "Write exactly 3 sentences. Sentence 1: summarize yesterday. "
            "Sentence 2: one data observation. Sentence 3: set an intention for today. "
            "No greetings. No questions. Only reference the data provided."
        )
        user_prompt = (
            f"Yesterday's wellness score: {score}/100 ({label}). "
            f"Avg stress: {stress:.0f}/100. Wellbeing: {wellbeing:.0f}/100. "
            f"Activation: {activation:.0f}/100. Calm time: {calm_min:.0f} min. "
            f"Peak stress: {peak_stress:.0f}/100."
        )
        return await self._ollama_generate(system_prompt, user_prompt, max_chars=400)

    def _get_coach_note_template(self, score, label, stress, wellbeing, activation, calm_min, peak_stress) -> str:
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

    # ============ Wellness Score (Feature #1) ============

    def _compute_wellness_components(self, s: Dict) -> float:
        """
        Shared Wellness Score formula: 7 voice scores + recovery, weighted by validity.
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

    def compute_wellness_score(self, db, yesterday_summary: Dict) -> Dict[str, Any]:
        """Compute today's Wellness Score from yesterday's data with fixed daily wellness weights."""
        if not yesterday_summary:
            return {'score': 0, 'has_data': False}

        today = date.today()
        dow = today.weekday()  # 0=Monday

        # Fixed weights — daily resilience + recovery score
        profile_name = 'Daily Wellness'

        score = self._compute_wellness_components(yesterday_summary)

        # Store in DB
        db.set_wellness_score(today.isoformat(), score, dow, profile_name)

        return {
            'score': score,
            'has_data': True,
            'date': today.isoformat(),
            'profile': profile_name,
            'day_of_week': dow,
        }

    def compute_intraday_wellness_score(self, db) -> Dict[str, Any]:
        """Compute today's live intraday Wellness Score. Requires 1+ reading today."""
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

        score = self._compute_wellness_components(today_summary)

        return {
            'score': score,
            'has_data': True,
            'reading_count': reading_count,
            'readings_needed': 0,
            'profile': "Today's Wellness",
            'date': date.today().isoformat(),
        }

    def get_top_wellness_contributor(self, db) -> str:
        """Find which component contributes most to today's wellness score."""
        today_summary = db.compute_daily_summary()
        if not today_summary:
            return "Voice"

        components = [
            ('stress',              0.15, True),
            ('wellbeing',           0.13, False),
            ('depression_risk',     0.13, True),
            ('activation',          0.13, False),
            ('calm',                0.12, False),
            ('anxiety_risk',        0.12, True),
            ('emotional_stability', 0.12, False),
        ]

        raw = {}
        raw['stress'] = today_summary.get('avg_stress')
        raw['wellbeing'] = today_summary.get('avg_wellbeing') or today_summary.get('avg_mood')
        raw['activation'] = today_summary.get('avg_activation') or today_summary.get('avg_energy')
        raw['calm'] = today_summary.get('avg_calm')
        raw['depression_risk'] = today_summary.get('avg_depression_risk')
        raw['anxiety_risk'] = today_summary.get('avg_anxiety_risk')
        raw['emotional_stability'] = today_summary.get('avg_emotional_stability')

        labels = {
            'stress': 'low stress',
            'wellbeing': 'wellbeing',
            'depression_risk': 'low depression risk',
            'activation': 'energy',
            'calm': 'calm',
            'anxiety_risk': 'low anxiety',
            'emotional_stability': 'stability',
        }

        best_key = None
        best_contribution = -1
        for key, weight, inverted in components:
            val = raw.get(key)
            if val is None:
                continue
            val = min(100, max(0, val))
            if inverted:
                val = 100 - val
            contribution = weight * val
            if contribution > best_contribution:
                best_contribution = contribution
                best_key = key

        if best_key:
            return f"Driven by {labels[best_key]}"
        return "Voice"

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

        # Wellness scores
        wellness_scores = []
        for s in this_week:
            cs = db.get_wellness_score(s['date'])
            wellness_scores.append(cs['score'] if cs else 0)
        avg_wellness = sum(wellness_scores) / len(wellness_scores) if wellness_scores else 0

        # Previous week wellness for trend
        prev_wellness = 0
        if prev_week:
            prev_scores = []
            for s in prev_week:
                cs = db.get_wellness_score(s['date'])
                prev_scores.append(cs['score'] if cs else 0)
            prev_wellness = sum(prev_scores) / len(prev_scores) if prev_scores else 0

        wellness_trend = avg_wellness - prev_wellness

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
        stress_delta = 0
        if prev_week:
            pw_stress = sum(s.get('avg_stress', 50) or 50 for s in prev_week) / len(prev_week)
            wow['stress'] = round(tw_stress - pw_stress, 1)
            stress_delta = round(tw_stress - pw_stress, 1)
            pw_wellbeing = sum(s.get('avg_wellbeing', s.get('avg_mood', 50)) or 50 for s in prev_week) / len(prev_week)
            wow['wellbeing'] = round(tw_wellbeing - pw_wellbeing, 1)

        # Calmest day (lowest avg stress)
        calmest_day = min(this_week, key=lambda s: s.get('avg_stress', 50) or 50)

        # Current streak: consecutive days with data (from most recent backwards)
        streak = 0
        for s in this_week:
            day_readings = db.get_readings_for_date(date.fromisoformat(s['date']))
            if len(day_readings) > 0:
                streak += 1
            else:
                break

        # Day data for overlay day circles
        day_data = []
        for s in sorted(this_week, key=lambda s: s['date']):
            d = date.fromisoformat(s['date'])
            day_readings = db.get_readings_for_date(d)
            day_data.append({
                'date': s['date'],
                'has_data': len(day_readings) > 0,
                'day_name': day_names[d.weekday()],
            })

        return {
            'has_data': True,
            'week_ending': this_week[0]['date'],
            'wellness': {
                'avg': round(avg_wellness),
                'trend': round(wellness_trend, 1),
                'daily': wellness_scores,
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
            'calmest_day': {
                'date': calmest_day['date'],
                'label': day_label(calmest_day['date']),
                'stress': round(calmest_day.get('avg_stress', 50) or 50),
            },
            'avg_stress': round(tw_stress, 1),
            'stress_delta': stress_delta,
            'streak': streak,
            'day_data': day_data,
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
        """Generate evening recap via LLM with template fallback."""
        if not today_summary or not today_readings:
            return "Your day is just beginning. Check back this evening for a recap."

        # Try LLM first
        recap = await self._generate_evening_recap_llm(today_summary, today_readings)
        if not recap:
            recap = self._generate_evening_recap_template(today_summary, today_readings)
        return recap

    async def _generate_evening_recap_llm(self, today_summary: Dict, today_readings: List[Dict]) -> Optional[str]:
        """Try to generate an evening recap via Ollama."""
        avg_stress = today_summary.get('avg_stress', 50)
        peak_stress = today_summary.get('peak_stress', 0)
        calm_time = today_summary.get('time_in_calm_min', 0)
        stressed_time = today_summary.get('time_in_stressed_min', 0)
        meetings = today_summary.get('total_meetings', 0)
        reading_count = len(today_readings)

        peak_time = ""
        if today_readings:
            peak_reading = max(today_readings, key=lambda r: r.get('stress_score', 0))
            peak_timestamp = datetime.fromisoformat(peak_reading['timestamp'])
            peak_time = peak_timestamp.strftime("%-I:%M %p")

        system_prompt = (
            "You are a voice wellness coach writing an evening recap. "
            "Write exactly 3 sentences. Sentence 1: describe the day's arc. "
            "Sentence 2: one highlight or observation. Sentence 3: a recovery tip for tonight. "
            "No greetings. No questions. Only reference the data provided."
        )
        user_prompt = (
            f"Avg stress: {avg_stress:.0f}/100. Peak stress: {peak_stress:.0f}/100"
            f"{f' around {peak_time}' if peak_time else ''}. "
            f"Calm time: {calm_time:.0f} min. Stressed time: {stressed_time:.0f} min. "
            f"Meetings: {meetings}. Total readings: {reading_count}."
        )
        return await self._ollama_generate(system_prompt, user_prompt, max_chars=400)

    def _generate_evening_recap_template(self, today_summary: Dict, today_readings: List[Dict]) -> str:
        """Generate evening recap from templates (original logic)."""
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
        Wellness score must be resolved async by the caller.

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
        wellness_yesterday = db.get_wellness_score(yesterday.isoformat())

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
            'wellness_yesterday': wellness_yesterday,
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

    async def generate_clarity_weekly_checkin(self, progress: Dict[str, Any]) -> Optional[str]:
        """Generate an AI coach weekly check-in for the Clarity Journey."""
        if not progress:
            return None

        track = progress.get('track_name', 'wellness')
        week = progress.get('current_week', 1)
        baseline = progress.get('baseline_score') or 0
        current = progress.get('current_score') or 0
        target = progress.get('target_score') or 0
        completion = progress.get('completion', {})
        rate = round((completion.get('overall_rate', 0)) * 100)
        phase = progress.get('phase', 'calibration')
        delta = round(current - baseline, 1)

        system_prompt = (
            "You are a supportive wellness coach for a voice-based wellness app. "
            "Write a brief, warm weekly check-in (2-3 sentences) for the user's Clarity Journey. "
            "Reference their specific metrics. Be encouraging but honest. No emojis."
        )

        user_prompt = (
            f"Week {week} of 12, {track} track ({phase} phase). "
            f"Baseline: {baseline}, Current: {current}, Target: {target}. "
            f"Change from baseline: {'+' if delta >= 0 else ''}{delta}. "
            f"Action completion rate: {rate}%. "
            f"Write a personalized weekly check-in."
        )

        result = await self._ollama_generate(system_prompt, user_prompt, max_chars=400)
        if result:
            return result

        # Template fallback
        if delta > 0:
            return (
                f"Week {week} check-in: Your {track.lower()} score has improved by {delta} points from your baseline. "
                f"With {rate}% of actions completed, you're building solid habits. Keep this momentum going."
            )
        else:
            return (
                f"Week {week} check-in: Building {track.lower()} takes time. "
                f"You've completed {rate}% of your actions so far. "
                f"Focus on consistency this week — small daily steps compound into real change."
            )
