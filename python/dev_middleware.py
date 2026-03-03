"""
Dev middleware and API endpoints for Lucid Steel Dev build.
Adds request logging, database inspection, and debug tools.
Only loaded when LUCID_DEV_MODE=1.
"""
import time
import json
import logging
import sqlite3
import gc
import os
import sys
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger('lucid.dev')

# ============ Request Logger Middleware ============

# Ring buffer of last 200 requests
_request_log = deque(maxlen=200)


class DevRequestLoggerMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request with method, path, status, and latency."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        entry = {
            'ts': datetime.now().isoformat(),
            'method': request.method,
            'path': request.url.path,
            'status': response.status_code,
            'latency_ms': round(elapsed_ms, 1),
        }
        _request_log.append(entry)

        if elapsed_ms > 1000:
            logger.warning("Slow request: %s %s -> %d (%.0fms)",
                           request.method, request.url.path, response.status_code, elapsed_ms)

        return response


# ============ Dev API Router ============

dev_router = APIRouter(prefix="/api/dev", tags=["dev"])


@dev_router.get("/status")
async def dev_status():
    """Quick status for the floating dev toolbar."""
    import psutil
    process = psutil.Process()
    mem_mb = round(process.memory_info().rss / (1024 * 1024))

    # Get reading count from DB
    reading_count = 0
    try:
        import api.dependencies as deps
        if deps.db:
            reading_count = deps.db.conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    except Exception:
        pass

    return {
        "memory_mb": mem_mb,
        "reading_count": reading_count,
        "pid": os.getpid(),
        "uptime_sec": round(time.monotonic()),
    }


@dev_router.get("/request-log")
async def get_request_log(limit: int = 50):
    """Return recent HTTP request log entries."""
    entries = list(_request_log)
    return entries[-limit:]


@dev_router.get("/tables")
async def list_tables():
    """List all SQLite tables and their row counts."""
    import api.dependencies as deps
    if not deps.db:
        return JSONResponse(status_code=503, content={"error": "DB not ready"})

    try:
        tables = deps.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        result = []
        for (name,) in tables:
            count = deps.db.conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
            result.append({"name": name, "rows": count})
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@dev_router.get("/table/{name}")
async def get_table_contents(name: str, limit: int = 100, offset: int = 0):
    """Browse table contents (read-only)."""
    import api.dependencies as deps
    if not deps.db:
        return JSONResponse(status_code=503, content={"error": "DB not ready"})

    try:
        # Validate table name exists
        exists = deps.db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        if not exists:
            return JSONResponse(status_code=404, content={"error": f"Table '{name}' not found"})

        # Get columns
        cols = [desc[1] for desc in deps.db.conn.execute(f"PRAGMA table_info([{name}])").fetchall()]

        # Get rows
        rows = deps.db.conn.execute(
            f"SELECT * FROM [{name}] LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()

        total = deps.db.conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]

        return {
            "table": name,
            "columns": cols,
            "rows": [list(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@dev_router.post("/query")
async def run_query(request: Request):
    """Execute a read-only SQL query."""
    import api.dependencies as deps
    if not deps.db:
        return JSONResponse(status_code=503, content={"error": "DB not ready"})

    body = await request.json()
    sql = body.get("sql", "").strip()
    if not sql:
        return JSONResponse(status_code=400, content={"error": "No SQL provided"})

    # Safety: only allow SELECT and PRAGMA
    sql_upper = sql.upper().lstrip()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("PRAGMA")):
        return JSONResponse(status_code=403, content={"error": "Only SELECT and PRAGMA queries allowed"})

    try:
        cursor = deps.db.conn.execute(sql)
        cols = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return {
            "columns": cols,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@dev_router.post("/reset-database")
async def reset_database():
    """Drop all data and reinitialize the database. Destructive!"""
    import api.dependencies as deps
    if not deps.db:
        return JSONResponse(status_code=503, content={"error": "DB not ready"})

    try:
        tables = deps.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        for (name,) in tables:
            if name.startswith('sqlite_'):
                continue
            deps.db.conn.execute(f"DELETE FROM [{name}]")
        deps.db.conn.execute("VACUUM")
        deps.db.conn.commit()
        return {"success": True, "tables_cleared": len(tables)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@dev_router.get("/debug-snapshot")
async def debug_snapshot():
    """Export a comprehensive debug snapshot."""
    import psutil
    import api.dependencies as deps

    process = psutil.Process()
    mem = process.memory_info()

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "pid": os.getpid(),
        "python_version": sys.version,
        "memory": {
            "rss_mb": round(mem.rss / (1024 * 1024)),
            "vms_mb": round(mem.vms / (1024 * 1024)),
        },
        "recent_requests": list(_request_log)[-20:],
    }

    # Orchestrator state
    if deps.orchestrator:
        snapshot["orchestrator"] = {
            "is_running": getattr(deps.orchestrator, 'is_running', None),
            "is_paused": getattr(deps.orchestrator, 'is_paused', None),
        }

    # DB stats
    if deps.db:
        try:
            tables = deps.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            snapshot["db_tables"] = {}
            for (name,) in tables:
                count = deps.db.conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
                snapshot["db_tables"][name] = count
        except Exception:
            pass

    return snapshot


@dev_router.post("/force-gc")
async def force_gc():
    """Force Python garbage collection."""
    before = len(gc.get_objects())
    collected = gc.collect()
    after = len(gc.get_objects())
    return {
        "collected": collected,
        "objects_before": before,
        "objects_after": after,
    }


def install_dev_middleware(fastapi_app):
    """Install dev middleware and routes onto the FastAPI app."""
    fastapi_app.add_middleware(DevRequestLoggerMiddleware)
    fastapi_app.include_router(dev_router)
    logger.info("Dev middleware and /api/dev/* endpoints installed")
