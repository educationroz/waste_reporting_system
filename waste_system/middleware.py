"""
waste_system/middleware.py
Custom middleware for the waste reporting system.
"""

import contextvars
import logging
from django.utils.cache import add_never_cache_headers

# Thread-local storage for correlation ID
_request_id_var = contextvars.ContextVar('request_id', default=None)

logger = logging.getLogger(__name__)


def get_current_request_id():
    """Return the correlation ID for the current request, or None if not set."""
    return _request_id_var.get()


class CorrelationIdMiddleware:
    """Add a unique correlation ID to every request for traceable logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import uuid
        correlation_id = request.META.get('HTTP_X_CORRELATION_ID') or uuid.uuid4().hex[:12]
        request.correlation_id = correlation_id

        # Set context variable for logging
        token = _request_id_var.set(correlation_id)

        # Add to response headers for client-side tracing
        response = self.get_response(request)
        response['X-Correlation-ID'] = correlation_id

        # Reset context variable
        _request_id_var.reset(token)
        return response


class NoCacheForAuthenticatedMiddleware:
    """Authenticated user le heko kunai pani page browser cache ma basna
    dinna — role/session change vaepachi same URL ma stale (aru user ko)
    HTML serve huna baata jogaucha."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            add_never_cache_headers(response)
        return response


class SecurityHeadersMiddleware:
    """CSP + hardening headers. Last so it sees the final response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        from django.conf import settings

        # Content-Security-Policy
        csp_mode = getattr(settings, 'CSP_MODE', 'compat')
        csp_report_uri = getattr(settings, 'CSP_REPORT_URI', '')

        if csp_mode == 'strict':
            csp = self._strict_csp(csp_report_uri)
        elif csp_mode == 'report':
            csp = self._report_csp(csp_report_uri)
        else:
            csp = self._compat_csp(csp_report_uri)

        response['Content-Security-Policy'] = csp
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(self), microphone=(), camera=(self), payment=()'
        response['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'SAMEORIGIN'

        return response

    def _compat_csp(self, report_uri):
        """Old permissive behaviour ('unsafe-inline' script-src)."""
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com "
            "https://accounts.google.com https://apis.google.com https://ssl.gstatic.com https://www.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://unpkg.com https://fonts.googleapis.com https://accounts.google.com https://apis.google.com; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://unpkg.com https://accounts.google.com https://apis.google.com; "
            "img-src 'self' data: blob: https: https://tile.openstreetmap.org https://a.tile.openstreetmap.org "
            "https://b.tile.openstreetmap.org https://c.tile.openstreetmap.org; "
            "connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://unpkg.com https://accounts.google.com https://apis.google.com "
            "https://ssl.gstatic.com https://www.gstatic.com https://nominatim.openstreetmap.org "
            "https://router.project-osrm.org https://oauth2.googleapis.com https://www.googleapis.com "
            "https://tile.openstreetmap.org https://a.tile.openstreetmap.org "
            "https://b.tile.openstreetmap.org https://c.tile.openstreetmap.org; "
            "frame-src 'self' https://accounts.google.com https://apis.google.com; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "worker-src 'self' blob:; "
            "manifest-src 'self';"
        )
        if report_uri:
            csp += f" report-uri {report_uri};"
        return csp

    def _report_csp(self, report_uri):
        """Strict policy but in Report-Only mode so violations show up without breaking anything."""
        csp = self._strict_csp(report_uri)
        return csp.replace('Content-Security-Policy', 'Content-Security-Policy-Report-Only')

    def _strict_csp(self, report_uri):
        """Enforce nonce + 'strict-dynamic' policy."""
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'nonce-{csp_nonce}' 'strict-dynamic' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
            "style-src 'self' 'nonce-{csp_nonce}' 'strict-dynamic' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob: https: https://tile.openstreetmap.org https://a.tile.openstreetmap.org "
            "https://b.tile.openstreetmap.org https://c.tile.openstreetmap.org; "
            "connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://unpkg.com https://accounts.google.com https://apis.google.com "
            "https://ssl.gstatic.com https://www.gstatic.com https://nominatim.openstreetmap.org "
            "https://router.project-osrm.org https://oauth2.googleapis.com https://www.googleapis.com "
            "https://tile.openstreetmap.org https://a.tile.openstreetmap.org "
            "https://b.tile.openstreetmap.org https://c.tile.openstreetmap.org; "
            "frame-src 'self' https://accounts.google.com https://apis.google.com; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "worker-src 'self' blob:; "
            "manifest-src 'self';"
        )
        if report_uri:
            csp += f" report-uri {report_uri};"
        return csp


def csp_nonce(request):
    """Expose CSP nonce to templates (used by SecurityHeadersMiddleware)."""
    import secrets
    if not hasattr(request, '_csp_nonce'):
        request._csp_nonce = secrets.token_urlsafe(16)
    return {'csp_nonce': request._csp_nonce}