"""
Settings, notifications, webhooks, and public API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException, Request
from urllib.parse import urlparse
import ipaddress

from api import dependencies as deps
from api.exceptions import DatabaseNotReady
from api.constants import ALLOWED_TRIGGER_TYPES, ALLOWED_CONDITION_OPS
from api.schemas import NotifPrefRequest, WebhookRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_webhook_url(url: str):
    """Validate webhook URL to prevent SSRF attacks."""
    parsed = urlparse(url)

    # Only allow http/https schemes
    if parsed.scheme not in ('http', 'https'):
        raise HTTPException(status_code=400, detail="URL must use http or https scheme")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid URL: no hostname")

    # Block localhost and loopback
    if hostname in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
        raise HTTPException(status_code=400, detail="Localhost URLs are not allowed")

    # Block private/link-local IP ranges
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Private/reserved IP addresses are not allowed")
    except ValueError:
        pass  # hostname is not an IP -- that's fine


@router.get("/api/notifications/prefs")
async def get_notification_prefs():
    """Get notification preferences"""
    if deps.db is None:
        raise DatabaseNotReady()
    prefs = deps.db.get_all_notification_prefs()
    # Fill defaults
    defaults = {
        'notifications_enabled': 'true',
        'quiet_start': '19',
        'quiet_end': '8',
        'notif_threshold': 'true',
        'notif_transition': 'true',
        'notif_milestone': 'true',
        'notif_echo': 'true',
        'notif_voice_weather': 'true',
        'notif_curtain_call': 'true',
        'notif_weekly_wrapped': 'true',
    }
    for k, v in defaults.items():
        if k not in prefs:
            prefs[k] = v
    return prefs


@router.post("/api/notifications/prefs")
async def set_notification_pref(req: NotifPrefRequest):
    """Set a notification preference"""
    if deps.db is None:
        raise DatabaseNotReady()
    deps.db.set_notification_pref(req.key, req.value)
    return {'success': True}


@router.get("/api/notifications/log")
async def get_notification_log(limit: int = 50):
    """Get recent notification history"""
    if deps.db is None:
        raise DatabaseNotReady()
    return {'log': deps.db.get_notification_log(limit=limit)}


@router.post("/api/webhooks")
async def register_webhook(req: WebhookRequest):
    """Register a new webhook"""
    if deps.db is None:
        raise DatabaseNotReady()

    # Validate URL (SSRF prevention)
    _validate_webhook_url(req.url)

    # Validate trigger type
    if req.trigger_type not in ALLOWED_TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid trigger_type. Must be one of: {', '.join(ALLOWED_TRIGGER_TYPES)}")

    # Validate condition operator if provided
    if req.condition_op and req.condition_op not in ALLOWED_CONDITION_OPS:
        raise HTTPException(status_code=400, detail=f"Invalid condition_op. Must be one of: {', '.join(ALLOWED_CONDITION_OPS)}")

    webhook_id = deps.db.add_webhook(
        url=req.url,
        trigger_type=req.trigger_type,
        condition_field=req.condition_field,
        condition_op=req.condition_op,
        condition_value=req.condition_value,
    )
    return {'success': True, 'id': webhook_id}


@router.get("/api/webhooks")
async def list_webhooks():
    """List all registered webhooks"""
    if deps.db is None:
        raise DatabaseNotReady()
    return {'webhooks': deps.db.get_webhooks(active_only=False)}


@router.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: int):
    """Delete a webhook"""
    if deps.db is None:
        raise DatabaseNotReady()
    deps.db.delete_webhook(webhook_id)
    return {'success': True}


@router.get("/api/v1/readings")
async def api_v1_readings(request: Request, limit: int = 50):
    """Public-style API for readings with simple token auth"""
    if deps.db is None:
        raise DatabaseNotReady()

    # Check API token
    token = request.headers.get('X-API-Token') or request.query_params.get('token')
    stored_token = deps.db.get_user_state('api_token', '')
    if not stored_token:
        # Auto-generate token on first use
        import secrets
        stored_token = secrets.token_urlsafe(32)
        deps.db.set_user_state('api_token', stored_token)

    if token != stored_token:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")

    readings = deps.db.get_readings(limit=limit)
    return {'readings': readings, 'count': len(readings)}


@router.get("/api/settings/linguistic-analysis")
async def get_linguistic_analysis_setting():
    """Get the enhanced linguistic analysis preference.

    When enabled (default), runs spaCy NER + pronoun/absolutist analysis + semantic coherence.
    User can disable for privacy or performance reasons.
    """
    if deps.db is None:
        raise DatabaseNotReady()
    value = deps.db.get_user_state('linguistic_analysis_enhanced', 'true')
    return {'enabled': value.lower() == 'true'}


@router.post("/api/settings/linguistic-analysis")
async def set_linguistic_analysis_setting(request: Request):
    """Set the enhanced linguistic analysis preference."""
    if deps.db is None:
        raise DatabaseNotReady()
    body = await request.json()
    enabled = bool(body.get('enabled', True))
    deps.db.set_user_state('linguistic_analysis_enhanced', 'true' if enabled else 'false')
    return {'success': True, 'enabled': enabled}


@router.get("/api/v1/token")
async def get_api_token(request: Request):
    """Get or generate the API token (for settings display)"""
    # Only allow from localhost
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Token endpoint is localhost-only")

    if deps.db is None:
        raise DatabaseNotReady()

    token = deps.db.get_user_state('api_token', '')
    if not token:
        import secrets
        token = secrets.token_urlsafe(32)
        deps.db.set_user_state('api_token', token)

    return {'token': token}
