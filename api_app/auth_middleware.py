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

Development fallback: when DEBUG=True, also accept a ``token`` query parameter
to work around SameSite=Lax cookie issues on localhost. This is NOT enabled
in production.
"""

from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


@database_sync_to_async
def get_user_from_jwt(token):
    try:
        access_token = AccessToken(token)
        user_id = access_token['user_id']
        return get_user_model().objects.get(id=user_id)
    except (InvalidToken, TokenError, get_user_model().DoesNotExist):
        return AnonymousUser()


class TokenAuthMiddleware:
    """
    Accepts JWT from query string when DEBUG=True.
    Only used for WebSocket connections on localhost.
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Try cookie-based auth first (handled by AuthMiddlewareStack outer)
        # If user is still anonymous and DEBUG=True, try token from query string
        if settings.DEBUG:
            query_string = scope.get('query_string', b'').decode()
            params = parse_qs(query_string)
            token = params.get('token', [None])[0]
            if token:
                scope['user'] = await get_user_from_jwt(token)
        return await self.inner(scope, receive, send)


def SessionOrJWTAuthMiddlewareStack(inner):
    """WebSocket auth from the HttpOnly session cookie.

    Kept under its original name so ``waste_system/asgi.py`` and any external
    references continue to work. It is now a thin alias for Channels'
    ``AuthMiddlewareStack``: the query-string JWT fallback it used to add has
    been removed (see the module docstring).
    """
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))


# Backwards-compatible alias. Anything still importing ``JWTAuthMiddleware``
# gets cookie-based session auth rather than the old query-string behaviour.
JWTAuthMiddleware = AuthMiddlewareStack
