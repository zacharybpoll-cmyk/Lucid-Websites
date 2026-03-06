"""
Voice Profile — trait derivation and insight generation from existing reading data.
"""
import logging
from datetime import datetime, timedelta, date
from fastapi import APIRouter
from api import dependencies as deps

logger = logging.getLogger('lucid.voice_profile')

router = APIRouter(prefix="/api", tags=["voice_profile"])


@router.get("/voice-profile")
async def get_voice_profile():
    """Derive voice traits and insights from accumulated reading data."""
    db = deps.db
    if db is None:
        return {"traits": [], "insights": [], "data_quality": {"reading_count": 0, "days_tracked": 0, "sufficient": False}}

    # Get all readings from last 90 days
    start_date = date.today() - timedelta(days=90)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
    readings = db.get_readings(start_time=start_time, limit=10000)

    if not readings:
        return {"traits": [], "insights": [], "data_quality": {"reading_count": 0, "days_tracked": 0, "sufficient": False}}

    # Data quality
    dates_set = set()
    for r in readings:
        ts = r.get('timestamp', '')
        if ts:
            dates_set.add(ts.split('T')[0])

    reading_count = len(readings)
    days_tracked = len(dates_set)
    sufficient = days_tracked >= 7

    # === Trait Derivation ===
    traits = []

    def _avg(key):
        vals = [r.get(key) for r in readings if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def _std(key):
        vals = [r.get(key) for r in readings if r.get(key) is not None]
        if len(vals) < 2:
            return None
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return variance ** 0.5

    # Speech Rate trait
    sr_avg = _avg('speech_rate')
    sr_std = _std('speech_rate')
    if sr_avg is not None and sr_std is not None and sr_std > 0:
        # Compare to population: mean=4.2, std=0.9
        z = (sr_avg - 4.2) / 0.9
        if z > 0.8:
            traits.append("Fast-paced")
        elif z < -0.8:
            traits.append("Measured")

    # Pitch Range trait (f0_std)
    f0_std_avg = _avg('f0_std')
    if f0_std_avg is not None:
        z = (f0_std_avg - 28.0) / 12.0
        if z > 0.8:
            traits.append("Expressive")
        elif z < -0.8:
            traits.append("Steady")

    # Filler Rate trait
    fr_avg = _avg('filler_rate')
    if fr_avg is not None:
        z = (fr_avg - 6.0) / 3.5
        if z < -0.5:
            traits.append("Polished")
        elif z > 0.8:
            traits.append("Spontaneous")

    # Hedging Score trait
    hs_avg = _avg('hedging_score')
    if hs_avg is not None:
        z = (hs_avg - 3.0) / 2.0
        if z > 0.8:
            traits.append("Cautious")
        elif z < -0.5:
            traits.append("Assertive")

    # Pause/speech rate regularity
    if sr_std is not None and sr_avg is not None and sr_avg > 0:
        cv = sr_std / sr_avg  # coefficient of variation
        if cv > 0.25:
            traits.append("Dynamic")
        elif cv < 0.10:
            traits.append("Fluid")

    # Limit to top 3
    traits = traits[:3]

    # === Insight Derivation ===
    insights = []

    # 1. Best clarity time (by day of week + hour)
    try:
        hour_clarity = {}
        for r in readings:
            ts = r.get('timestamp', '')
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                continue
            hour = dt.hour
            hnr = r.get('hnr')
            sr = r.get('speech_rate')
            if hnr is not None and sr is not None:
                if hour not in hour_clarity:
                    hour_clarity[hour] = []
                # Clarity proxy: HNR + normalized speech rate
                hour_clarity[hour].append(hnr + sr * 2)

        if hour_clarity:
            best_hour = max(hour_clarity, key=lambda h: sum(hour_clarity[h]) / len(hour_clarity[h]) if hour_clarity[h] else 0)
            hour_label = f"{best_hour}am" if best_hour < 12 else (f"{best_hour - 12}pm" if best_hour > 12 else "12pm")

            # Also check day of week
            dow_clarity = {}
            for r in readings:
                ts = r.get('timestamp', '')
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except Exception:
                    continue
                dow = dt.strftime('%A')
                hnr = r.get('hnr')
                sr = r.get('speech_rate')
                if hnr is not None and sr is not None:
                    if dow not in dow_clarity:
                        dow_clarity[dow] = []
                    dow_clarity[dow].append(hnr + sr * 2)

            best_dow = max(dow_clarity, key=lambda d: sum(dow_clarity[d]) / len(dow_clarity[d]) if dow_clarity[d] else 0) if dow_clarity else None

            if best_dow:
                insights.append({
                    "icon": "clock-calendar",
                    "text": f"You speak most clearly on {best_dow} mornings around {hour_label}",
                    "type": "clarity_pattern"
                })
    except Exception as e:
        logger.warning(f"Failed to compute clarity pattern: {e}")

    # 2. Energy peak hour
    try:
        hour_energy = {}
        for r in readings:
            ts = r.get('timestamp', '')
            energy = r.get('energy_score')
            if not ts or energy is None:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                continue
            hour = dt.hour
            if hour not in hour_energy:
                hour_energy[hour] = []
            hour_energy[hour].append(energy)

        if hour_energy:
            best_energy_hour = max(hour_energy, key=lambda h: sum(hour_energy[h]) / len(hour_energy[h]) if hour_energy[h] else 0)
            hour_label = f"{best_energy_hour}am" if best_energy_hour < 12 else (f"{best_energy_hour - 12}pm" if best_energy_hour > 12 else "12pm")
            insights.append({
                "icon": "chart-up",
                "text": f"Your vocal energy peaks around {hour_label}",
                "type": "energy_peak"
            })
    except Exception as e:
        logger.warning(f"Failed to compute energy peak: {e}")

    # 3. Cognitive load pattern (meeting vs non-meeting)
    try:
        meeting_readings = [r for r in readings if r.get('meeting_detected') == 1]
        non_meeting_readings = [r for r in readings if r.get('meeting_detected') != 1]

        if len(meeting_readings) >= 5 and len(non_meeting_readings) >= 5:
            meeting_stress = sum(r.get('stress_score', 50) for r in meeting_readings) / len(meeting_readings)
            non_meeting_stress = sum(r.get('stress_score', 50) for r in non_meeting_readings) / len(non_meeting_readings)

            diff = meeting_stress - non_meeting_stress
            if diff > 8:
                insights.append({
                    "icon": "calendar-stack",
                    "text": f"Your stress is {int(diff)} points higher during meetings",
                    "type": "cognitive_load"
                })
            elif diff < -5:
                insights.append({
                    "icon": "calendar-stack",
                    "text": "Meetings don't seem to increase your stress levels",
                    "type": "cognitive_load"
                })
    except Exception as e:
        logger.warning(f"Failed to compute cognitive load: {e}")

    # 4. Pitch range insight
    try:
        if f0_std_avg is not None:
            z = (f0_std_avg - 28.0) / 12.0
            if z > 0.5:
                insights.append({
                    "icon": "waveform",
                    "text": "You have a naturally wide pitch range — a sign of vocal expressiveness",
                    "type": "pitch_range"
                })
            elif z < -0.5:
                insights.append({
                    "icon": "waveform",
                    "text": "Your pitch range is narrow and consistent — a calm, measured speaking style",
                    "type": "pitch_range"
                })
    except Exception as e:
        logger.warning(f"Failed to compute pitch range: {e}")

    # Limit to 4 insights
    insights = insights[:4]

    return {
        "traits": traits,
        "insights": insights,
        "data_quality": {
            "reading_count": reading_count,
            "days_tracked": days_tracked,
            "sufficient": sufficient
        }
    }
