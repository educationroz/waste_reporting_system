"""
waste_system/middleware.py

Request-level middleware for correlation IDs and structured logging context.

- CorrelationIdMiddleware: generates a unique request ID (UUID4) and attaches
  it to the request, response header, and logging context so every log line
  emitted during a request can be traced back to the exact HTTP call that
  triggered it.
"""

import logging
import uuid

import threading

# Thread-local storage for the current request's correlation ID.
_thread_locals = threading.local()


def get_current_request_id():
    """Return the correlation ID for the current request, or None."""
    return getattr(_thread_locals, 'request_id', None)


class CorrelationIdMiddleware:
    """Add a unique request ID to every request and response.

    The ID is:
    - Generated as a UUID4 for each incoming request.
    - Set on ``request.request_id`` so views/serializers can access it.
    - Added to the response header ``X-Request-ID`` for client-side tracing.
    - Stored in a thread-local so the JsonFormatter can include it in log lines.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex
        request.request_id = request_id
        _thread_locals.request_id = request_id

        response = self.get_response(request)
        response['X-Request-ID'] = request_id

        # Clean up thread-local after the request completes.
        _thread_locals.request_id = None
        return response
