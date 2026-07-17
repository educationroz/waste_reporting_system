"""
Custom authentication middleware for WebSocket connections with JWT tokens.
Extracts JWT token from query parameters and authenticates the connection.

TEMP DEBUG VERSION — logs exactly why authentication fails instead of
silently returning AnonymousUser(). Revert to the original once the
notification WS issue is diagnosed (or just remove the print/logger lines).
"""

import logging
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed

logger = logging.getLogger('ws_auth_debug')
logging.basicConfig(level=logging.INFO)


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom middleware for JWT authentication in WebSocket connections.
    Expects the JWT token to be passed as a query parameter: ?token=<jwt_token>
    """

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'websocket':
            await super().__call__(scope, receive, send)
            return

        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        path = scope.get('path')
        logger.info(f'[WS AUTH] path={path} token_present={bool(token)} token_prefix={token[:12] if token else None}')

        scope['user'] = await self.authenticate_user(token)

        logger.info(f'[WS AUTH] path={path} resolved_user={scope["user"]} is_authenticated={scope["user"].is_authenticated}')

        await super().__call__(scope, receive, send)

    @database_sync_to_async
    def authenticate_user(self, token):
        if not token:
            logger.warning('[WS AUTH] No token provided in query string.')
            return AnonymousUser()

        try:
            jwt_auth = JWTAuthentication()
            validated_token = jwt_auth.get_validated_token(token)
            user = jwt_auth.get_user(validated_token)
            return user
        except (InvalidToken, AuthenticationFailed) as exc:
            logger.warning(f'[WS AUTH] Token invalid/expired: {exc}')
            return AnonymousUser()
        except Exception as exc:
            logger.error(f'[WS AUTH] Unexpected error during WS auth: {exc!r}')
            return AnonymousUser()