"""Security response headers (Content-Security-Policy and friends).

WHY THIS EXISTS
---------------
Auth moved off ``localStorage`` onto an ``HttpOnly`` session cookie, so injected
JavaScript can no longer *read* the credential. This middleware is the second
layer: it constrains what injected JavaScript can *do*.

THE ``'unsafe-inline'`` PROBLEM AND HOW WE RETIRE IT
----------------------------------------------------
This app has ~166 inline ``onclick=``/``onchange=`` attributes and ~30 inline
``<script>`` blocks. A policy that simply drops ``'unsafe-inline'`` would stop
all of them and break the UI, so the header shipped permissive and the docstring
promised a refactor "later". That is the classic way a CSP never gets tightened.

Instead this module now supports three modes, selected by ``CSP_MODE``:

``compat``  (default)
    ``script-src 'self' 'unsafe-inline' <cdns>``. Exactly the old behaviour.
    Inline handlers keep working. Does NOT stop script injection.

``report``
    Sends the *strict* nonce-based policy as
    ``Content-Security-Policy-Report-Only`` **and** the permissive policy as the
    enforced ``Content-Security-Policy``. Nothing breaks, but the browser
    reports every violation to ``CSP_REPORT_URI``. This is how you discover the
    real inline-handler inventory in production before enforcing.

``strict``
    Enforces the nonce-based policy: ``script-src 'self' 'nonce-<random>'
    'strict-dynamic'``. Inline handler attributes stop executing — only switch
    once ``report`` mode is quiet.

Because ``'strict-dynamic'`` is present in strict mode, a nonce'd loader script
may inject further scripts (that is how bundlers work) while host allow-lists
are ignored by supporting browsers. The CDN list is kept in the policy anyway as
a fallback for older browsers that do not understand ``'strict-dynamic'``.

USING THE NONCE IN TEMPLATES
----------------------------
The middleware puts a fresh base64 nonce on ``request.csp_nonce`` for every
request, and a context processor exposes it as ``{{ csp_nonce }}``. Add it to
inline script tags as ``nonce="{{ csp_nonce }}"``. Tags carrying a valid nonce
keep working in every mode, so templates can be migrated incrementally.

WHAT THE POLICY BUYS YOU EVEN IN COMPAT MODE
--------------------------------------------
* ``connect-src`` — fetch/XHR/WebSocket may only reach our own origin plus the
  CDNs/map APIs we actually use, so injected JS cannot POST a scraped session to
  ``evil.example``.
* ``form-action`` — an injected ``<form>`` cannot submit credentials off-site.
* ``base-uri`` — blocks ``<base href>`` hijacking of every relative URL.
* ``object-src 'none'`` — no Flash/applet legacy vectors.
* ``frame-ancestors`` — clickjacking protection (the modern X-Frame-Options).
"""

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
    'https://oauth2.googleapis.com',
    'https://www.googleapis.com',
)

# Font/style origins used by the Google Sign-In widget and Bootstrap Icons.
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

    directives = [
        "default-src 'self'",
        # style-src keeps 'unsafe-inline': there are ~116 inline style="..."
        # attributes, and unlike scripts, inline CSS is not a code-execution
        # vector in modern browsers (expression() died with IE).
        f"style-src 'self' 'unsafe-inline' {cdns} {styles}",
        f"font-src 'self' data: {fonts} {cdns}",
        # Map tiles are <img> loads; https: already covers every tile server.
        "img-src 'self' data: blob: https:",
        # The important one: where injected JS is allowed to send data.
        f"connect-src 'self' {ws_scheme} {cdns} {map_apis}",
        "frame-src 'self' https://accounts.google.com https://apis.google.com",
        "frame-ancestors 'self'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        # Legacy plugin/worker hardening.
        "worker-src 'self' blob:",
        "manifest-src 'self'",
    ]
    if is_secure:
        directives.append('upgrade-insecure-requests')
    return directives


def _permissive_script_src() -> str:
    return f"script-src 'self' 'unsafe-inline' {' '.join(CDN_HOSTS)}"


def _strict_script_src(nonce: str) -> str:
    # 'strict-dynamic' lets a nonce'd script load its own dependencies while
    # telling modern browsers to ignore the host allow-list. The CDN hosts stay
    # for browsers without 'strict-dynamic' support.
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
        # report-uri is deprecated but still the only directive Safari honours;
        # report-to is the modern replacement. Send both.
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
        # Generate the nonce BEFORE the view runs so templates can use it.
        nonce = generate_nonce()
        request.csp_nonce = nonce

        response = self.get_response(request)

        mode = getattr(settings, 'CSP_MODE', 'compat')
        if mode not in VALID_MODES:
            mode = 'compat'

        is_secure = request.is_secure()

        # Don't fight the Django debug toolbar / admin docs in local dev.
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
                    # Enforce the permissive policy, but measure the strict one.
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
        # COOP: Google Identity Services (GSI) uses cross-origin postMessage
        # during login. On auth pages (/login/, /register/), omit COOP so the browser
        # does not log COOP postMessage diagnostic warnings. On all other pages,
        # enforce same-origin-allow-popups.
        if not request.path.startswith(('/login', '/register', '/auth/')):
            response.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
        response.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
        response.setdefault('X-Content-Type-Options', 'nosniff')
        return response
