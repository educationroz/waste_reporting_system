"""Security response headers (Content-Security-Policy and friends).

WHY THIS EXISTS
---------------
Auth moved off ``localStorage`` onto an ``HttpOnly`` session cookie, so injected
JavaScript can no longer *read* the credential. This middleware is the second
layer: it constrains what injected JavaScript can *do*.

ABOUT ``script-src`` AND ``'unsafe-inline'``
-------------------------------------------
The honest caveat: this app has ~164 inline ``onclick=``/``onchange=``
attributes and ~30 inline ``<script>`` blocks. A nonce- or hash-based
``script-src`` would refuse to run all of them and would break the UI
outright, so ``'unsafe-inline'`` stays for now. That means this CSP does **not**
stop script injection.

What it *does* stop is the part that turns an XSS bug into a breach:

* ``connect-src`` — fetch/XHR/WebSocket can only talk to our own origin and the
  handful of CDNs we actually use. An injected script cannot POST scraped data
  (or a stolen session) to ``evil.example``.
* ``form-action`` — injected ``<form>`` cannot submit credentials off-site.
* ``base-uri`` — blocks ``<base href>`` hijacking of every relative URL.
* ``object-src 'none'`` — no Flash/applet legacy vectors.
* ``frame-ancestors`` — clickjacking protection (the modern X-Frame-Options).

Tightening ``script-src`` properly means moving those inline handlers into
``addEventListener`` calls in external JS files. That is a mechanical but
wide-reaching refactor, deliberately kept out of this security fix so the
change stays reviewable. Until then, treat output escaping as the primary XSS
defence, not this header.
"""

CDN_HOSTS = (
    'https://cdn.jsdelivr.net',
    'https://cdnjs.cloudflare.com',
    'https://unpkg.com',
    'https://accounts.google.com',
)

# Third-party HTTP APIs the app genuinely calls with fetch()/XHR. These MUST
# be in connect-src or the browser blocks the request outright.
#
#   nominatim  — reverse geocoding: turns the photo's GPS pin into a street
#                address and auto-fills "Pickup Address" on the home form.
#                Blocking it left the field empty and the report unsubmittable.
#   osrm       — road routing for the driver dashboard and route planning.
#
# Keep this list tight: connect-src is what stops injected JS exfiltrating
# data, so every entry here is somewhere an attacker could POST to.
MAP_API_HOSTS = (
    'https://nominatim.openstreetmap.org',
    'https://router.project-osrm.org',
)


def _policy(is_secure: bool) -> str:
    ws_scheme = 'wss:' if is_secure else 'ws: wss:'
    cdns = ' '.join(CDN_HOSTS)
    map_apis = ' '.join(MAP_API_HOSTS)
    directives = [
        "default-src 'self'",
        # See module docstring: 'unsafe-inline' is required by the existing
        # inline handlers. Not a strict policy — connect-src is doing the work.
        f"script-src 'self' 'unsafe-inline' {cdns}",
        f"style-src 'self' 'unsafe-inline' {cdns} https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com " + cdns,
        # Map tiles are <img> loads; https: already covers every tile server.
        "img-src 'self' data: blob: https:",
        # The important one: where injected JS is allowed to send data.
        f"connect-src 'self' {ws_scheme} {cdns} {map_apis}",
        "frame-src 'self' https://accounts.google.com",
        "frame-ancestors 'self'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
    if is_secure:
        directives.append('upgrade-insecure-requests')
    return '; '.join(directives)


class SecurityHeadersMiddleware:
    """Adds CSP + a few smaller hardening headers to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Don't fight the Django debug toolbar / admin docs in local dev.
        if 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = _policy(request.is_secure())

        response.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.setdefault(
            'Permissions-Policy',
            'geolocation=(self), microphone=(), camera=(self), payment=()',
        )
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        return response
