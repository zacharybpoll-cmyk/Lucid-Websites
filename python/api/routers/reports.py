"""
Reports — clinical preview data, PDF generation, and export history.
"""
import io
import logging
from datetime import datetime, timedelta, date
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from api import dependencies as deps

logger = logging.getLogger('lucid.reports')

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/clinical-preview")
async def clinical_preview(days: int = Query(default=90, ge=7, le=365)):
    """Return stress trend data, grove participation, and flagged health events for the Reports tab."""
    db = deps.db
    if db is None:
        return {"has_data": False}

    summaries = db.get_daily_summaries(days=days)
    if not summaries:
        return {"has_data": False, "days": days}

    summaries = sorted(summaries, key=lambda s: s['date'])

    # Stress trend data
    stress_trend = [
        {"date": s["date"], "stress": s.get("avg_stress", 50) or 50}
        for s in summaries
    ]

    # Zone summary
    total_calm = sum(s.get('time_in_calm_min', 0) or 0 for s in summaries)
    total_steady = sum(s.get('time_in_steady_min', 0) or 0 for s in summaries)
    total_tense = sum(s.get('time_in_tense_min', 0) or 0 for s in summaries)
    total_stressed = sum(s.get('time_in_stressed_min', 0) or 0 for s in summaries)
    total_time = max(1, total_calm + total_steady + total_tense + total_stressed)

    zone_summary = {
        "calm_pct": round(total_calm / total_time * 100, 1),
        "steady_pct": round(total_steady / total_time * 100, 1),
        "tense_pct": round(total_tense / total_time * 100, 1),
        "stressed_pct": round(total_stressed / total_time * 100, 1),
    }

    # Grove participation
    grove_data = []
    try:
        from backend.engagement import EngagementTracker
        tracker = EngagementTracker(db)
        grove = tracker.compute_grove()
        grove_data = grove.get("calendar", []) if grove else []
    except Exception as e:
        logger.warning(f"Failed to compute grove: {e}")

    # Flagged health events from echoes
    flagged_events = []
    try:
        echoes = db.get_echoes(limit=50)
        for echo in echoes:
            if echo.get("severity", "info") in ("warning", "alert"):
                flagged_events.append({
                    "date": echo.get("timestamp", "")[:10],
                    "type": echo.get("echo_type", ""),
                    "message": echo.get("message", ""),
                    "severity": echo.get("severity", "info"),
                })
    except Exception as e:
        logger.warning(f"Failed to load echoes: {e}")

    # Pattern flags & readings for enriched data
    start_date = date.today() - timedelta(days=days)
    start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
    readings = []
    try:
        readings = db.get_readings(start_time=start_time, limit=5000) or []
    except Exception as e:
        logger.warning(f"Failed to load readings: {e}")

    try:
        from backend.pattern_detector import PatternDetector
        if readings:
            detector = PatternDetector()
            patterns = detector.detect(readings, summaries)
            for p in patterns:
                if p.get("severity") in ("warning", "alert"):
                    flagged_events.append({
                        "date": p.get("date", date.today().isoformat()),
                        "type": p.get("pattern_type", ""),
                        "message": p.get("description", ""),
                        "severity": p.get("severity", "info"),
                    })
    except Exception as e:
        logger.warning(f"Failed to detect patterns: {e}")

    # --- Enriched clinical data from readings ---

    def _safe_avg(values):
        """Average a list, skipping None values. Returns None if empty."""
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 2) if clean else None

    # Acoustic summary
    acoustic_summary = {
        "avg_f0": _safe_avg([r.get("f0_mean") for r in readings]),
        "avg_hnr": _safe_avg([r.get("hnr") for r in readings]),
        "avg_speech_rate": _safe_avg([r.get("speech_rate") for r in readings]),
        "avg_alpha_ratio": _safe_avg([r.get("alpha_ratio") for r in readings]),
    }

    # Linguistic summary
    linguistic_summary = {
        "avg_filler_rate": _safe_avg([r.get("filler_rate") for r in readings]),
        "avg_hedging_rate": _safe_avg([r.get("hedging_rate") for r in readings]),
        "avg_negative_sentiment": _safe_avg([r.get("negative_sentiment") for r in readings]),
        "avg_lexical_diversity": _safe_avg([r.get("lexical_diversity") for r in readings]),
        "avg_pronoun_i_ratio": _safe_avg([r.get("pronoun_i_ratio") for r in readings]),
    }

    # Depression / anxiety trends
    phq9_values = [r.get("phq9_mapped") for r in readings if r.get("phq9_mapped") is not None]
    gad7_values = [r.get("gad7_mapped") for r in readings if r.get("gad7_mapped") is not None]

    def _severity_distribution(values, thresholds):
        """Bucket values into severity categories."""
        dist = {label: 0 for _, label in thresholds}
        for v in values:
            for ceiling, label in thresholds:
                if v <= ceiling:
                    dist[label] += 1
                    break
        return dist

    phq9_thresholds = [(4, "minimal"), (9, "mild"), (14, "moderate"), (19, "mod_severe"), (27, "severe")]
    gad7_thresholds = [(4, "minimal"), (9, "mild"), (14, "moderate"), (21, "severe")]

    depression_anxiety = {
        "avg_phq9_mapped": _safe_avg(phq9_values),
        "avg_gad7_mapped": _safe_avg(gad7_values),
        "phq9_severity_distribution": _severity_distribution(phq9_values, phq9_thresholds) if phq9_values else None,
        "gad7_severity_distribution": _severity_distribution(gad7_values, gad7_thresholds) if gad7_values else None,
    }

    # Week-over-week comparison
    now = date.today()
    last_7d = [r for r in readings if r.get("timestamp") and r["timestamp"][:10] >= (now - timedelta(days=7)).isoformat()]
    prior_7d = [r for r in readings if r.get("timestamp") and (now - timedelta(days=14)).isoformat() <= r["timestamp"][:10] < (now - timedelta(days=7)).isoformat()]

    week_over_week = {
        "last_7d": {
            "avg_stress": _safe_avg([r.get("stress") for r in last_7d]),
            "avg_wellbeing": _safe_avg([r.get("wellbeing") for r in last_7d]),
            "avg_depression": _safe_avg([r.get("depression") for r in last_7d]),
            "reading_count": len(last_7d),
        },
        "prior_7d": {
            "avg_stress": _safe_avg([r.get("stress") for r in prior_7d]),
            "avg_wellbeing": _safe_avg([r.get("wellbeing") for r in prior_7d]),
            "avg_depression": _safe_avg([r.get("depression") for r in prior_7d]),
            "reading_count": len(prior_7d),
        },
    }

    # Notable patterns: day-of-week stress variation
    from collections import defaultdict
    dow_stress = defaultdict(list)
    for r in readings:
        ts = r.get("timestamp")
        stress_val = r.get("stress")
        if ts and stress_val is not None:
            try:
                day_name = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%A")
                dow_stress[day_name].append(stress_val)
            except (ValueError, TypeError):
                pass

    notable_patterns = {
        "day_of_week_stress": {
            day: round(sum(vals) / len(vals), 1)
            for day, vals in dow_stress.items() if vals
        },
        "meeting_impact": None,  # Placeholder — requires calendar integration
    }

    # Therapist flags
    therapist_flags = []

    # Elevated self-focus language (pronoun-I ratio > 0.10)
    avg_pronoun_i = linguistic_summary["avg_pronoun_i_ratio"]
    if avg_pronoun_i is not None and avg_pronoun_i > 0.10:
        therapist_flags.append({
            "flag": "elevated_self_focus",
            "detail": f"Average pronoun-I ratio {avg_pronoun_i:.3f} exceeds threshold (0.10)",
        })

    # Rising stress trend (last 7d avg > prior 7d avg by 5+ points)
    last_stress = week_over_week["last_7d"]["avg_stress"]
    prior_stress = week_over_week["prior_7d"]["avg_stress"]
    if last_stress is not None and prior_stress is not None and (last_stress - prior_stress) >= 5:
        therapist_flags.append({
            "flag": "rising_stress_trend",
            "detail": f"Stress increased from {prior_stress:.1f} to {last_stress:.1f} week-over-week",
        })

    # Vocabulary contraction (lexical diversity < 0.40)
    avg_lex = linguistic_summary["avg_lexical_diversity"]
    if avg_lex is not None and avg_lex < 0.40:
        therapist_flags.append({
            "flag": "vocabulary_contraction",
            "detail": f"Lexical diversity {avg_lex:.3f} below clinical threshold (0.40)",
        })

    return {
        "has_data": True,
        "days": days,
        "days_tracked": len(summaries),
        "total_readings": sum(s.get("reading_count", 0) or 0 for s in summaries),
        "stress_trend": stress_trend,
        "zone_summary": zone_summary,
        "grove_calendar": grove_data[:days],
        "flagged_events": flagged_events[:20],
        "acoustic_summary": acoustic_summary,
        "linguistic_summary": linguistic_summary,
        "depression_anxiety": depression_anxiety,
        "week_over_week": week_over_week,
        "notable_patterns": notable_patterns,
        "therapist_flags": therapist_flags,
    }


@router.get("/pdf")
async def generate_pdf(days: int = Query(default=90, ge=7, le=365)):
    """Generate a clinical PDF report."""
    db = deps.db
    if db is None:
        return {"error": "Not initialized"}

    try:
        from backend.report_generator import WellnessReportGenerator
        gen = WellnessReportGenerator(db)
        pdf_bytes = gen.generate(days=days)

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=lucid_wellness_report_{days}d.pdf"}
        )
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return {"error": str(e)}


@router.get("/export-history")
async def export_history():
    """List previously generated reports (from local tracking)."""
    # For now, return empty list — history tracking can be added later
    return {"exports": []}
