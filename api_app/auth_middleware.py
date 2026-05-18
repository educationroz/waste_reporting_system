"""
Custom authentication middleware for WebSocket connections with JWT tokens.
Extracts JWT token from query parameters and authenticates the connection.
"""

import json
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom middleware for JWT authentication in WebSocket connections.
    Expects the JWT token to be passed as a query parameter: ?token=<jwt_token>
    """

    async def __call__(self, scope, receive, send):
        # Only apply to WebSocket connections
        if scope['type'] != 'websocket':
            await super().__call__(scope, receive, send)
            return

        # Extract token from query parameters
        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        # Authenticate the user
        scope['user'] = await self.authenticate_user(token)

        await super().__call__(scope, receive, send)

    @database_sync_to_async
    def authenticate_user(self, token):
        """
        Authenticate the user using the provided JWT token.
        Returns the authenticated User or AnonymousUser if authentication fails.
        """
        if not token:
            return AnonymousUser()

        try:
            jwt_auth = JWTAuthentication()
            # Create a mock request object with the token
            from rest_framework.request import Request
            from django.http import HttpRequest
            
            http_request = HttpRequest()
            http_request.META['HTTP_AUTHORIZATION'] = f'Bearer {token}'
            drf_request = Request(http_request)
            
            # Validate and get the user
            validated_token = jwt_auth.get_validated_token(token)
            user = jwt_auth.get_user(validated_token)
            
            return user
        except (InvalidToken, AuthenticationFailed):
            return AnonymousUser()
        except Exception:
            return AnonymousUser()
