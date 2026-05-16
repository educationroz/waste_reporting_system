"""
waste_system/asgi.py
Handles both HTTP and WebSocket connections via Channels.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'waste_system.settings')
django.setup()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

import api_app.routing

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                api_app.routing.websocket_urlpatterns
            )
        )
    ),
})