from django.urls import path

from .consumers import DriverLocationConsumer, NotificationConsumer, WasteRequestConsumer

websocket_urlpatterns = [
    path('ws/requests/',        WasteRequestConsumer.as_asgi()),
    path('ws/driver-locations/', DriverLocationConsumer.as_asgi()),
    path('ws/notifications/',   NotificationConsumer.as_asgi()),
]