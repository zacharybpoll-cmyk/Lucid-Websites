"""
The Bridge — Webhook Manager for Attune
Dispatches POST requests to registered webhook URLs when conditions are met.
"""
import logging
import threading
import time
from typing import Dict, List, Any, Optional
import json

logger = logging.getLogger('attune.webhook')


class WebhookManager:
    """Manages webhook registrations and dispatches."""

    def __init__(self, db):
        self.db = db

    def dispatch(self, trigger_type: str, payload: Dict[str, Any]):
        """
        Check all active webhooks for the given trigger type.
        Fire matching webhooks in background threads.
        """
        webhooks = self.db.get_webhooks(active_only=True)
        matching = [w for w in webhooks if w['trigger_type'] == trigger_type]

        for webhook in matching:
            # Check condition if specified
            if webhook.get('condition_field') and webhook.get('condition_op'):
                field_val = payload.get(webhook['condition_field'])
                if field_val is None:
                    continue
                threshold = webhook.get('condition_value', 0)
                op = webhook['condition_op']
                if op == '>' and not (field_val > threshold):
                    continue
                if op == '<' and not (field_val < threshold):
                    continue
                if op == '>=' and not (field_val >= threshold):
                    continue
                if op == '<=' and not (field_val <= threshold):
                    continue
                if op == '==' and not (field_val == threshold):
                    continue

            # Fire webhook in background
            threading.Thread(
                target=self._fire_webhook,
                args=(webhook['url'], trigger_type, payload),
                daemon=True
            ).start()

    def _fire_webhook(self, url: str, trigger_type: str, payload: Dict[str, Any]):
        """POST to webhook URL with retry."""
        import urllib.request
        import urllib.error

        body = json.dumps({
            'event': trigger_type,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'data': payload
        }).encode('utf-8')

        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                urllib.request.urlopen(req, timeout=10)
                return
            except (urllib.error.URLError, Exception) as e:
                if attempt == 0:
                    time.sleep(5)  # Retry after 5s
                else:
                    logger.error(f"Failed to deliver to {url}: {e}")

    def on_reading(self, reading: Dict[str, Any]):
        """Dispatch reading-related webhooks."""
        self.dispatch('reading', {
            'stress_score': reading.get('stress_score'),
            'mood_score': reading.get('mood_score'),
            'energy_score': reading.get('energy_score'),
            'calm_score': reading.get('calm_score'),
            'zone': reading.get('zone'),
            'meeting_detected': reading.get('meeting_detected'),
        })

    def on_zone_change(self, old_zone: str, new_zone: str, reading: Dict[str, Any]):
        """Dispatch zone transition webhooks."""
        self.dispatch('zone_change', {
            'old_zone': old_zone,
            'new_zone': new_zone,
            'stress_score': reading.get('stress_score'),
        })
