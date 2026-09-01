"""Security response headers (Content-Security-Policy and friends)."""

import base64
import os

from django.conf import settings

CDN_HOSTS = (
    'https://cdn.jsdelivr.net',
    'https://cdnjs.cloudflare.com',
    'https://unpkg.com',
    'https://accounts.google.com',
    'https://apis.google.com',
    'https://ssl.gstatic.com',
    'https://www.gstatic.com',
)

# Third-party HTTP APIs the app genuinely calls with fetch()/XHR.
MAP_API_HOSTS = (
    'https://nominatim.openstreetmap.org',
    'https://router.project-osrm.org',
    'https://oauth2.googleapis.com',
    'https://www.googleapis.com',
)

# OpenStreetMap tile servers for Leaflet maps
TILE_SERVERS = (
    'https://tile.openstreetmap.org',
    'https://a.tile.openstreetmap.org',
    'https://b.tile.openstreetmap.org',
    'https://c.tile.openstreetmap.org',
)

FONT_HOSTS = ('https://fonts.gstatic.com',)
STYLE_HOSTS = ('https://fonts.googleapis.com',)

VALID_MODES = ('compat', 'report', 'strict')

def generate_nonce() -> str:
    """A fresh 128-bit base64 nonce. Must be unpredictable per response."""
    return base64.b64encode(os.urandom(16)).decode('ascii')

def _shared_directives(is_secure: bool) -> list:
    """Directives that are identical in the permissive and strict policies."""
    ws_scheme = 'wss:' if is_secure else 'ws: wss:'
    cdns = ' '.join(CDN_HOSTS)
    map_apis = ' '.join(MAP_API_HOSTS)
    styles = ' '.join(STYLE_HOSTS)
    fonts = ' '.join(FONT_HOSTS)
    tiles = ' '.join(TILE_SERVERS)

    directives = [
        "default-src 'self'",
        f"style-src 'self' 'unsafe-inline' {cdns} {styles}",
        f"font-src 'self' data: {fonts} {cdns}",
        # Map tiles are <img> loads; explicitly allow tile.openstreetmap.org
        f"img-src 'self' data: blob: https: {tiles}",
        f"connect-src 'self' {ws_scheme} {cdns} {map_apis} {tiles}",
        "frame-src 'self' https://accounts.google.com https://apis.google.com",
        "frame-ancestors 'self'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "worker-src 'self' blob:",
        "manifest-src 'self'",
    ]
    if is_secure:
        directives.append('upgrade-insecure-requests')
    
    # THIS RETURN STATEMENT IS CRITICAL
    return directives

def _permissive_script_src() -> str:
    return f"script-src 'self' 'unsafe-inline' {' '.join(CDN_HOSTS)}"

def _strict_script_src(nonce: str) -> str:
    return (
        f"script-src 'self' 'nonce-{nonce}' 'strict-dynamic' "
        f"{' '.join(CDN_HOSTS)}"
    )

def build_policy(is_secure: bool, nonce: str, strict: bool) -> str:
    directives = _shared_directives(is_secure)
    script_src = _strict_script_src(nonce) if strict else _permissive_script_src()
    directives.insert(1, script_src)

    report_uri = getattr(settings, 'CSP_REPORT_URI', '')
    if report_uri:
        directives.append(f'report-uri {report_uri}')
        directives.append('report-to csp-endpoint')

    return '; '.join(directives)

def csp_nonce(request):
    """Context processor: exposes ``{{ csp_nonce }}`` to every template."""
    return {'csp_nonce': getattr(request, 'csp_nonce', '')}

class SecurityHeadersMiddleware:
    """Adds CSP + a few smaller hardening headers to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nonce = generate_nonce()
        request.csp_nonce = nonce

        response = self.get_response(request)

        mode = getattr(settings, 'CSP_MODE', 'compat')
        if mode not in VALID_MODES:
            mode = 'compat'

        is_secure = request.is_secure()

        if 'Content-Security-Policy' not in response:
            if mode == 'strict':
                response['Content-Security-Policy'] = build_policy(
                    is_secure, nonce, strict=True
                )
            else:
                response['Content-Security-Policy'] = build_policy(
                    is_secure, nonce, strict=False
                )
                if mode == 'report':
                    response['Content-Security-Policy-Report-Only'] = (
                        build_policy(is_secure, nonce, strict=True)
                    )

        report_uri = getattr(settings, 'CSP_REPORT_URI', '')
        if report_uri:
            response.setdefault(
                'Reporting-Endpoints', f'csp-endpoint="{report_uri}"'
            )

        response.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.setdefault(
            'Permissions-Policy',
            'geolocation=(self), microphone=(), camera=(self), payment=()',
        )
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
        response.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
        response.setdefault('X-Content-Type-Options', 'nosniff')
        return response