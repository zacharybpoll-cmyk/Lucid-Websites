"""
Supabase REST API client for analytics.
Thin HTTP layer using httpx with retry + timeout.
"""
import logging
import time
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger('attune.supabase')

# Retry config
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds: 2, 4, 8
REQUEST_TIMEOUT = 10.0  # seconds


class SupabaseClient:
    """Lightweight Supabase REST client for analytics tables."""

    def __init__(self, url: str, key: str):
        self.rest_url = f"{url}/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT)
        return self._client

    def close(self):
        if self._client and not self._client.is_closed:
            self._client.close()

    def _request(self, method: str, table: str, json_data: Any,
                 extra_headers: Optional[Dict] = None) -> bool:
        """Make a request with exponential backoff retry. Returns True on success."""
        url = f"{self.rest_url}/{table}"
        headers = {**self.headers}
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(MAX_RETRIES):
            try:
                client = self._get_client()
                resp = client.request(method, url, json=json_data, headers=headers)
                if resp.status_code < 300:
                    return True
                logger.warning(f"Supabase {method} {table} returned {resp.status_code}: "
                               f"{resp.text[:200]}")
                # Don't retry client errors (4xx)
                if 400 <= resp.status_code < 500:
                    return False
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                logger.debug(f"Supabase {method} {table} attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            except Exception as e:
                logger.warning(f"Supabase unexpected error: {e}")
                return False

            if attempt < MAX_RETRIES - 1:
                delay = BACKOFF_BASE * (2 ** attempt)
                time.sleep(delay)

        logger.warning(f"Supabase {method} {table} failed after {MAX_RETRIES} attempts")
        return False

    def upsert_user(self, user_id: str, app_version: str, os_version: str) -> bool:
        """Upsert into analytics_users."""
        data = {
            "user_id": user_id,
            "last_seen_at": _now_iso(),
            "app_version": app_version,
            "os_version": os_version,
        }
        return self._request("POST", "analytics_users", data)

    def insert_events(self, events: List[Dict]) -> bool:
        """Bulk insert into analytics_events."""
        if not events:
            return True
        return self._request("POST", "analytics_events", events,
                             extra_headers={"Prefer": "return=minimal"})

    def insert_errors(self, errors: List[Dict]) -> bool:
        """Bulk insert into analytics_errors."""
        if not errors:
            return True
        return self._request("POST", "analytics_errors", errors,
                             extra_headers={"Prefer": "return=minimal"})

    def upsert_daily(self, summary: Dict) -> bool:
        """Upsert into analytics_daily."""
        return self._request("POST", "analytics_daily", summary)

    def mark_onboarding_complete(self, user_id: str) -> bool:
        """Set onboarding_completed flag on analytics_users."""
        data = {
            "user_id": user_id,
            "onboarding_completed": True,
            "onboarding_completed_at": _now_iso(),
        }
        return self._request("POST", "analytics_users", data)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
