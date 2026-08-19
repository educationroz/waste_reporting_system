"""Authentication middleware for WebSocket connections.

SECURITY (token-in-URL fix)
---------------------------
This middleware used to accept the JWT **only** as a query parameter
(``?token=<jwt>``). That had two problems:

1. It forced the browser to keep a readable copy of the access token in
   ``localStorage`` so JS could build the socket URL — which is exactly the
   XSS-exfiltration risk we are removing app-wide.
2. Query strings leak. They land in web-server access logs, proxy logs and
   ``Referer`` headers, so a short-lived credential ends up persisted in
   plaintext in places nobody is auditing.

Browsers cannot set an ``Authorization`` header on a WebSocket handshake, but
the handshake **is** a normal HTTP request, so it does send cookies. We
therefore authenticate browser sockets from the Django session cookie
(``HttpOnly``, unreadable to JS) via Channels' ``AuthMiddlewareStack``.

The ``?token=`` path is kept as a fallback for non-browser API clients
(mobile apps, scripts) that hold a JWT legitimately and have no session
cookie. Order matters: session first, JWT only if the session did not resolve
a user.
"""

import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

logger = logging.getLogger(__name__)


class JWTAuthMiddleware(BaseMiddleware):
    """Fallback JWT auth for WebSocket clients that have no session cookie.

    Expects ``?token=<jwt>``. Runs *inside* ``AuthMiddlewareStack`` (see
    ``SessionOrJWTAuthMiddlewareStack`` below), so ``scope['user']`` may
    already be a real user from the session — in that case we leave it alone
    and never look at the query string at all.
    """

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'websocket':
            await super().__call__(scope, receive, send)
            return

        existing = scope.get('user')
        if existing is not None and getattr(existing, 'is_authenticated', False):
            # Session cookie already identified the user — preferred path.
            await super().__call__(scope, receive, send)
            return

        token = parse_qs(scope.get('query_string', b'').decode()).get('token', [None])[0]
        if token:
            # Non-browser client. Note we never log the token itself.
            logger.debug('WS falling back to query-string JWT for %s', scope.get('path'))
            scope['user'] = await self.authenticate_user(token)
        else:
            scope['user'] = AnonymousUser()

        await super().__call__(scope, receive, send)

    @database_sync_to_async
    def authenticate_user(self, token):
        try:
            jwt_auth = JWTAuthentication()
            return jwt_auth.get_user(jwt_auth.get_validated_token(token))
        except (InvalidToken, AuthenticationFailed) as exc:
            logger.warning('WS JWT rejected: %s', exc)
            return AnonymousUser()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error('WS auth error: %r', exc)
            return AnonymousUser()


def SessionOrJWTAuthMiddlewareStack(inner):
    """Session-cookie auth first, query-string JWT only as a fallback."""
    return AuthMiddlewareStack(JWTAuthMiddleware(inner))
