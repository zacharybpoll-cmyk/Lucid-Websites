"""
Custom exception hierarchy for the Attune API.

These exceptions are caught by the global exception handler in routes.py
and converted to structured JSON error responses with appropriate HTTP
status codes and Retry-After headers.
"""


class AttuneError(Exception):
    """Base exception for Attune API errors."""
    def __init__(self, message: str, code: str, status_code: int = 500, retry_after: int = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


class DatabaseNotReady(AttuneError):
    def __init__(self):
        super().__init__("Database not initialized", "DB_NOT_READY", 503, 5)


class ModelNotLoaded(AttuneError):
    def __init__(self):
        super().__init__("Models still loading", "MODELS_LOADING", 503, 10)


class ServiceNotReady(AttuneError):
    def __init__(self, service: str = "Service"):
        super().__init__(f"{service} not initialized", "SERVICE_NOT_READY", 503, 5)
