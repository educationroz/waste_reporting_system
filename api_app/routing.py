from django.urls import path

from .consumers import (
    ComplaintConsumer,
    DriverLocationConsumer,
    NotificationConsumer,
    WasteRequestConsumer,
)

websocket_urlpatterns = [
    path('ws/requests/',        WasteRequestConsumer.as_asgi()),
    path('ws/driver-locations/', DriverLocationConsumer.as_asgi()),
    path('ws/notifications/',   NotificationConsumer.as_asgi()),
    path('ws/complaints/',      ComplaintConsumer.as_asgi()),
]