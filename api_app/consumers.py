import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


class WasteRequestConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time waste request updates.
    Connect: ws://localhost:8000/ws/requests/
    Broadcasts status changes to all connected clients in 'request_updates' group.
    """

    GROUP_NAME = 'request_updates'

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()
        await self.send(json.dumps({
            'type': 'connection_established',
            'message': f'Connected as {user.username}',
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data):
        """
        Handle incoming messages from client.
        Supported types:
          - ping: keepalive
          - request_update: broadcast status change (admin/driver only)
        """
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(json.dumps({'type': 'error', 'message': 'Invalid JSON.'}))
            return

        msg_type = data.get('type')

        if msg_type == 'ping':
            await self.send(json.dumps({'type': 'pong'}))

        elif msg_type == 'request_update':
            if self.user.role not in ('admin', 'driver'):
                await self.send(json.dumps({'type': 'error', 'message': 'Permission denied.'}))
                return
            await self.channel_layer.group_send(
                self.GROUP_NAME,
                {
                    'type': 'broadcast_request_update',
                    'request_id': data.get('request_id'),
                    'status': data.get('status'),
                    'updated_by': self.user.username,
                }
            )

    async def broadcast_request_update(self, event):
        """Called when group_send fires 'broadcast_request_update'."""
        await self.send(json.dumps({
            'type': 'request_update',
            'request_id': event['request_id'],
            'status': event['status'],
            'updated_by': event['updated_by'],
        }))


class DriverLocationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time driver GPS location tracking.
    Connect: ws://localhost:8000/ws/driver-locations/
    """

    GROUP_NAME = 'driver_locations'

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data):
        """Driver sends their GPS coordinates."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if self.user.role != 'driver':
            await self.send(json.dumps({'type': 'error', 'message': 'Drivers only.'}))
            return

        lat = data.get('latitude')
        lng = data.get('longitude')
        if lat is None or lng is None:
            return

        # Save to DB and get driver ID
        driver_id = await self.save_driver_location(lat, lng)
        
        if driver_id:
            # Broadcast to all (admins watching the map)
            await self.channel_layer.group_send(
                self.GROUP_NAME,
                {
                    'type': 'driver_location_update',
                    'driver_id': driver_id,
                    'driver_name': self.user.username,
                    'latitude': str(lat),
                    'longitude': str(lng),
                }
            )

    async def driver_location_update(self, event):
        await self.send(json.dumps({
            'type': 'driver_location',
            'driver_id': event['driver_id'],
            'driver_name': event['driver_name'],
            'latitude': event['latitude'],
            'longitude': event['longitude'],
        }))

    @database_sync_to_async
    def save_driver_location(self, lat, lng):
        from .models import Driver
        try:
            driver = Driver.objects.get(user=self.user)
            driver.current_latitude = lat
            driver.current_longitude = lng
            driver.save(update_fields=['current_latitude', 'current_longitude'])
            return driver.id
        except Driver.DoesNotExist:
            return None  # Silent fail - driver profile not created yet

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    Personal notification channel per user.
    Connect: ws://localhost:8000/ws/notifications/
    """

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f'notifications_user_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass  # Users only receive notifications, not send

    async def send_notification(self, event):
        """Called by group_send to push notification to user's socket."""
        await self.send(json.dumps({
            'type': 'notification',
            'title': event['title'],
            'message': event['message'],
            'notification_type': event['notification_type'],
        }))