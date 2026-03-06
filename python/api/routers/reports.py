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

    # Pattern flags
    try:
        from backend.pattern_detector import PatternDetector
        start_date = date.today() - timedelta(days=days)
        start_time = datetime.combine(start_date, datetime.min.time()).isoformat()
        readings = db.get_readings(start_time=start_time, limit=5000)
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

    return {
        "has_data": True,
        "days": days,
        "days_tracked": len(summaries),
        "total_readings": sum(s.get("reading_count", 0) or 0 for s in summaries),
        "stress_trend": stress_trend,
        "zone_summary": zone_summary,
        "grove_calendar": grove_data[:days],
        "flagged_events": flagged_events[:20],
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
