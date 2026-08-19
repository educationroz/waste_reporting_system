"""Authentication middleware for WebSocket connections.

SECURITY: session-cookie auth only — no credentials in the URL
--------------------------------------------------------------
This middleware previously accepted the JWT as a query parameter
(``?token=<jwt>``). That is removed.

Query strings are the wrong place for a credential. Even over TLS the URL is
not confidential to the endpoints handling it: it is written to reverse-proxy
and load-balancer access logs (nginx's ``$request`` includes the query string
by default), kept in browser history, and forwarded in ``Referer`` headers.
A JWT there ends up persisted in plaintext across systems nobody audits, and
it stays replayable until it expires.

Browsers cannot set an ``Authorization`` header on a WebSocket handshake, but
the handshake *is* an ordinary HTTP request, so it sends cookies. Channels'
``AuthMiddlewareStack`` resolves ``scope['user']`` from the Django session
cookie, which is ``HttpOnly`` and therefore unreadable to JavaScript. That
gives us authentication with no secret in the URL and no secret in JS.

Non-browser clients (mobile apps, scripts) authenticate the same way: POST
credentials to ``/auth/session-login/`` over HTTPS, keep the returned
``sessionid`` cookie, and send it on the handshake. Any standard WebSocket
library supports a ``Cookie`` header.

The consumers already reject unauthenticated connections (``close(code=4001)``
in ``api_app/consumers.py``), so an anonymous scope is refused at connect time.
"""

from channels.auth import AuthMiddlewareStack


def SessionOrJWTAuthMiddlewareStack(inner):
    """WebSocket auth from the HttpOnly session cookie.

    Kept under its original name so ``waste_system/asgi.py`` and any external
    references continue to work. It is now a thin alias for Channels'
    ``AuthMiddlewareStack``: the query-string JWT fallback it used to add has
    been removed (see the module docstring).
    """
    return AuthMiddlewareStack(inner)


# Backwards-compatible alias. Anything still importing ``JWTAuthMiddleware``
# gets cookie-based session auth rather than the old query-string behaviour.
JWTAuthMiddleware = AuthMiddlewareStack
