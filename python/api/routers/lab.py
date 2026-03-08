"""
Biomarker Lab endpoints.
Provides per-biomarker stats, sparklines, z-scores, and the voice fingerprint radar.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from api import dependencies as deps
from api.exceptions import DatabaseNotReady

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lab", tags=["lab"])

# ---------------------------------------------------------------------------
# Path to the metadata file — resolved relative to this source file so it
# works both in development (python/) and inside the packaged .app bundle.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_METADATA_PATH = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "data", "biomarker_metadata.json")
)

# Columns pulled from the readings table for lab queries
_LAB_COLUMNS = [
    "timestamp",
    "f0_mean", "f0_std", "jitter", "shimmer", "hnr",
    "rms_energy", "speech_rate", "spectral_centroid", "spectral_entropy",
    "zcr", "voice_breaks", "alpha_ratio", "mfcc3",
    "f1_mean", "f2_mean", "spectral_flux",
    "stress_score", "mood_score", "energy_score", "calm_score",
    "depression_raw", "anxiety_raw",
    "depression_mapped", "anxiety_mapped",
    "stress_score_raw",
    "depression_quantized", "anxiety_quantized",
    "filler_rate", "hedging_score", "negative_sentiment", "disfluency_rate",
    "lexical_diversity", "pronoun_i_ratio", "absolutist_ratio",
    "sentiment_valence", "sentiment_arousal", "semantic_coherence",
]

_LAB_SELECT = ", ".join(_LAB_COLUMNS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_metadata() -> Dict[str, Any]:
    """Load biomarker metadata JSON from disk."""
    try:
        with open(_METADATA_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        logger.error("biomarker_metadata.json not found at %s", _METADATA_PATH)
        return {"biomarkers": {}}
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse biomarker_metadata.json: %s", exc)
        return {"biomarkers": {}}


def _rows_to_dicts(rows) -> List[Dict[str, Any]]:
    """Convert sqlite3.Row objects to plain dicts."""
    return [dict(row) for row in rows]


def _safe_float(value) -> Optional[float]:
    """Return float or None; swallow non-numeric values."""
    if value is None:
        return None
    try:
        fval = float(value)
        import math
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval
    except (TypeError, ValueError):
        return None


def _compute_sparkline(rows: List[Dict], column: str, days: int = 14) -> List[Optional[float]]:
    """
    Build a list of daily averages (length=days), oldest first.
    Days with no data are None.
    """
    today = datetime.utcnow().date()
    buckets: Dict[str, List[float]] = {}

    for row in rows:
        val = _safe_float(row.get(column))
        if val is None:
            continue
        ts_str = row.get("timestamp", "")
        try:
            # Timestamps stored as "YYYY-MM-DD HH:MM:SS" or ISO with T
            ts = datetime.fromisoformat(ts_str.replace("T", " ").split(".")[0])
            day_key = ts.date().isoformat()
        except (ValueError, AttributeError):
            continue
        buckets.setdefault(day_key, []).append(val)

    result: List[Optional[float]] = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        vals = buckets.get(day)
        if vals:
            result.append(round(sum(vals) / len(vals), 4))
        else:
            result.append(None)
    return result


def _compute_z_score(value: float, mean: float, std: float) -> float:
    """Standard z-score; returns 0.0 when std is zero."""
    if std == 0.0:
        return 0.0
    return round((value - mean) / std, 3)


def _compute_range_position(value: float, rng_min: float, rng_max: float) -> float:
    """Clamp and normalise value to [0, 1] within the normal range."""
    span = rng_max - rng_min
    if span <= 0:
        return 0.5
    pos = (value - rng_min) / span
    return round(max(0.0, min(1.0, pos)), 3)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/biomarkers")
async def get_biomarkers():
    """
    Return the last-14-days biomarker stats for each tracked vocal feature.

    Response shape:
    {
      "biomarkers": {
        "<column>": {
          "meta": { ...metadata fields... },
          "latest_value": <float | null>,
          "sparkline": [<float | null>, ...],   // 14 daily averages, oldest first
          "z_score": <float>,
          "range_position": <float>,             // 0-1 within normal range
          "within_normal_range": <bool>
        },
        ...
      },
      "total_readings_14d": <int>,
      "as_of": "<ISO timestamp>"
    }
    """
    if deps.db is None:
        raise DatabaseNotReady()

    metadata = _load_metadata()
    biomarker_meta = metadata.get("biomarkers", {})

    # Pull last 14 days of readings
    try:
        with deps.db.lock:
            cursor = deps.db.conn.cursor()
            cursor.execute(
                f"""
                SELECT {_LAB_SELECT}
                FROM readings
                WHERE timestamp > datetime('now', '-14 days')
                ORDER BY timestamp DESC
                """,
            )
            rows = _rows_to_dicts(cursor.fetchall())
    except Exception as exc:
        logger.error("Lab /biomarkers DB query failed: %s", exc)
        rows = []

    result: Dict[str, Any] = {}

    for col, meta in biomarker_meta.items():
        # Latest non-null value
        latest_value: Optional[float] = None
        for row in rows:
            val = _safe_float(row.get(col))
            if val is not None:
                latest_value = val
                break  # rows are DESC by timestamp

        sparkline = _compute_sparkline(rows, col, days=14)

        pop_mean = meta.get("population_mean", 0.0) or 0.0
        pop_std = meta.get("population_std", 1.0) or 1.0
        normal_rng = meta.get("normal_range", {})
        rng_min = normal_rng.get("min", 0.0)
        rng_max = normal_rng.get("max", 1.0)

        if latest_value is not None:
            z_score = _compute_z_score(latest_value, pop_mean, pop_std)
            range_pos = _compute_range_position(latest_value, rng_min, rng_max)
            within_normal = (rng_min <= latest_value <= rng_max)
        else:
            z_score = 0.0
            range_pos = 0.5
            within_normal = True  # default neutral when no data

        result[col] = {
            "meta": meta,
            "latest_value": latest_value,
            "sparkline": sparkline,
            "z_score": z_score,
            "range_position": range_pos,
            "within_normal_range": within_normal,
        }

    return {
        "biomarkers": result,
        "total_readings_14d": len(rows),
        "as_of": datetime.utcnow().isoformat(),
    }


@router.get("/biomarker-history")
async def get_biomarker_history(column: str = "stress_score", days: int = 30):
    """
    Return daily averages for a single biomarker over a given period.
    Used by the trend chart in the bell curve modal.
    """
    if deps.db is None:
        raise DatabaseNotReady()

    # Validate column against whitelist (prevents SQL injection)
    if column not in _LAB_COLUMNS:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": f"Invalid column: {column}"})

    # Cap days to 365
    days = max(1, min(365, days))

    try:
        with deps.db.lock:
            cursor = deps.db.conn.cursor()
            cursor.execute(
                f"""
                SELECT timestamp, {column}
                FROM readings
                WHERE timestamp > datetime('now', '-{days} days')
                ORDER BY timestamp DESC
                """,
            )
            rows = _rows_to_dicts(cursor.fetchall())
    except Exception as exc:
        logger.error("Lab /biomarker-history DB query failed: %s", exc)
        rows = []

    daily_averages = _compute_sparkline(rows, column, days=days)
    today = datetime.utcnow().date()
    dates = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]

    return {
        "column": column,
        "days": days,
        "daily_averages": daily_averages,
        "dates": dates,
    }


@router.get("/fingerprint")
async def get_fingerprint():
    """
    Return voice fingerprint data: radar chart dimensions + unique-marker highlights.

    Response shape:
    {
      "radar": [{"dim": "Stress", "value": 65}, ...],
      "unique_markers": [
        {
          "name": "Vocal Brightness",
          "direction": "above average",
          "description": "Your voice sits brighter than 78% of voices"
        },
        ...
      ],
      "total_readings": <int>,
      "days_tracked": <int>
    }
    """
    if deps.db is None:
        raise DatabaseNotReady()

    metadata = _load_metadata()
    biomarker_meta = metadata.get("biomarkers", {})

    # Pull last 30 days for fingerprint
    try:
        with deps.db.lock:
            cursor = deps.db.conn.cursor()
            cursor.execute(
                f"""
                SELECT {_LAB_SELECT}
                FROM readings
                WHERE timestamp > datetime('now', '-30 days')
                ORDER BY timestamp DESC
                """,
            )
            rows = _rows_to_dicts(cursor.fetchall())

            # All-time count
            cursor.execute("SELECT COUNT(*) AS cnt FROM readings")
            total_readings_row = cursor.fetchone()
            total_readings = dict(total_readings_row)["cnt"] if total_readings_row else 0

            # Days tracked (distinct dates with at least one reading)
            cursor.execute(
                "SELECT COUNT(DISTINCT date(timestamp)) AS days FROM readings"
            )
            days_row = cursor.fetchone()
            days_tracked = dict(days_row)["days"] if days_row else 0

    except Exception as exc:
        logger.error("Lab /fingerprint DB query failed: %s", exc)
        rows = []
        total_readings = 0
        days_tracked = 0

    # ------------------------------------------------------------------
    # Aggregate per-column means over last 30 days
    # ------------------------------------------------------------------
    def _col_mean(col: str) -> Optional[float]:
        vals = [_safe_float(r.get(col)) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return sum(vals) / len(vals)

    stress_mean = _col_mean("stress_score")
    mood_mean = _col_mean("mood_score")
    energy_mean = _col_mean("energy_score")
    calm_mean = _col_mean("calm_score")
    jitter_mean = _col_mean("jitter")
    hnr_mean = _col_mean("hnr")
    spectral_flux_mean = _col_mean("spectral_flux")
    depression_mapped_mean = _col_mean("depression_mapped")

    # ------------------------------------------------------------------
    # 8 radar dimensions — all normalised to 0-100
    # ------------------------------------------------------------------
    def _pct(val: Optional[float], default: float = 50.0) -> float:
        return round(float(val), 1) if val is not None else default

    # vocal_steadiness: invert jitter (jitter ~0.001-0.04, scale x1000, invert)
    if jitter_mean is not None:
        # jitter * 1000 gives ~1-40 range; invert and scale to 0-100
        steadiness = max(0.0, min(100.0, 100.0 - (jitter_mean * 1000 / 0.04) * 100))
    else:
        steadiness = 50.0

    # voice_clarity: hnr normalised to 0-100 (normal range ~10-25 dB, clamp to 0-30)
    if hnr_mean is not None:
        clarity = max(0.0, min(100.0, (hnr_mean / 25.0) * 100.0))
    else:
        clarity = 50.0

    # speech_dynamism: spectral_flux normalised (typical range 0.001-0.05)
    if spectral_flux_mean is not None:
        dynamism = max(0.0, min(100.0, (spectral_flux_mean / 0.05) * 100.0))
    else:
        dynamism = 50.0

    # depression_risk: invert mapped PHQ-9 (0-27 → 100-0)
    if depression_mapped_mean is not None:
        dep_risk = max(0.0, min(100.0, 100.0 - (depression_mapped_mean / 27.0) * 100.0))
    else:
        dep_risk = 80.0  # default optimistic when no data

    radar = [
        {"dim": "Stress",            "value": round(100.0 - _pct(stress_mean, 50.0), 1)},
        {"dim": "Mood",              "value": _pct(mood_mean, 50.0)},
        {"dim": "Energy",            "value": _pct(energy_mean, 50.0)},
        {"dim": "Calm",              "value": _pct(calm_mean, 50.0)},
        {"dim": "Vocal Steadiness",  "value": round(steadiness, 1)},
        {"dim": "Voice Clarity",     "value": round(clarity, 1)},
        {"dim": "Speech Dynamism",   "value": round(dynamism, 1)},
        {"dim": "Depression Guard",  "value": round(dep_risk, 1)},
    ]

    # ------------------------------------------------------------------
    # Unique markers: find biomarkers with the largest abs(z_score)
    # ------------------------------------------------------------------
    import math

    z_scores: List[Dict[str, Any]] = []
    for col, meta in biomarker_meta.items():
        col_mean = _col_mean(col)
        if col_mean is None:
            continue
        pop_mean = meta.get("population_mean", 0.0) or 0.0
        pop_std = meta.get("population_std", 1.0) or 1.0
        z = _compute_z_score(col_mean, pop_mean, pop_std)
        if math.isnan(z) or math.isinf(z):
            continue
        z_scores.append({
            "col": col,
            "meta": meta,
            "z": z,
            "col_mean": col_mean,
            "pop_mean": pop_mean,
            "pop_std": pop_std,
        })

    # Sort by absolute z-score descending, take top 3
    z_scores.sort(key=lambda x: abs(x["z"]), reverse=True)
    top_unique = z_scores[:3]

    unique_markers: List[Dict[str, Any]] = []
    for item in top_unique:
        z = item["z"]
        meta = item["meta"]
        display_name = meta.get("display_name", item["col"])

        # Express z as a percentile approximation for plain-English description
        # Using a simple normal CDF approximation
        percentile = _z_to_percentile(z)

        if z > 0:
            direction = "above average"
            direction_adv = "higher than"
        else:
            direction = "below average"
            direction_adv = "lower than"

        pct_other = round(abs(percentile - 50) + 50) if z > 0 else round(50 - abs(percentile - 50))
        pct_other = max(51, min(99, pct_other))

        description = (
            f"Your {display_name.lower()} is {direction_adv} "
            f"{pct_other}% of voices"
        )

        unique_markers.append({
            "name": display_name,
            "direction": direction,
            "description": description,
            "z_score": round(z, 2),
        })

    return {
        "radar": radar,
        "unique_markers": unique_markers,
        "total_readings": total_readings,
        "days_tracked": days_tracked,
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _z_to_percentile(z: float) -> float:
    """
    Approximate normal CDF using the Abramowitz & Stegun rational approximation.
    Returns a percentile (0-100).
    """
    import math

    def _phi(x: float) -> float:
        """Cumulative distribution function for the standard normal."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    return round(_phi(z) * 100.0, 1)
