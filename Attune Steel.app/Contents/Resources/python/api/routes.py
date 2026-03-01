"""
FastAPI app -- includes all sub-routers and global exception handlers.
"""
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from pathlib import Path

from app_config import config
from api.exceptions import AttuneError, DatabaseNotReady, ModelNotLoaded, ServiceNotReady  # noqa: F401
from api.routers import health, readings, analysis, speaker, settings, dashboard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App & middleware
# ---------------------------------------------------------------------------

app = FastAPI(title="Attune API")

# CORS middleware — derive origins from configured port
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://127.0.0.1:{config.api_port}", f"http://localhost:{config.api_port}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(AttuneError)
async def attune_error_handler(request: Request, exc: AttuneError):
    headers = {}
    if exc.retry_after:
        headers["Retry-After"] = str(exc.retry_after)
    logger.warning("AttuneError on %s %s: [%s] %s", request.method, request.url.path, exc.code, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "code": exc.code, "retry_after": exc.retry_after},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unexpected exceptions — log and return structured 500."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "code": "INTERNAL_ERROR", "retry_after": None},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Include routers
app.include_router(health.router)
app.include_router(readings.router)
app.include_router(analysis.router)
app.include_router(speaker.router)
app.include_router(settings.router)
app.include_router(dashboard.router)


@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/static/index.html")


# Mount static files (frontend) - must be AFTER API routes
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
