"""
FastAPI dependency injection — replaces the global-variable pattern in routes.py.
Global references are set by main.py during startup.
"""
from fastapi import HTTPException

# Global references (set by main.py during startup)
db = None
orchestrator = None
meeting_detector = None
insight_engine = None
notification_manager = None
active_runner = None


def get_db():
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Database not initialized",
            headers={"Retry-After": "5"},
        )
    return db


def get_orchestrator():
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized",
            headers={"Retry-After": "5"},
        )
    return orchestrator


def get_meeting_detector():
    if meeting_detector is None:
        raise HTTPException(
            status_code=503,
            detail="Meeting detector not initialized",
            headers={"Retry-After": "5"},
        )
    return meeting_detector


def get_insight_engine():
    if insight_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Insight engine not initialized",
            headers={"Retry-After": "5"},
        )
    return insight_engine


def get_notification_manager():
    if notification_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Notification manager not initialized",
            headers={"Retry-After": "5"},
        )
    return notification_manager


def require_initialized():
    """FastAPI dependency that ensures core services are ready.
    Use with Depends() on endpoints that need the full system."""
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="System initializing — please retry",
            headers={"Retry-After": "5"},
        )
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Models loading — please retry",
            headers={"Retry-After": "10"},
        )
    return True
