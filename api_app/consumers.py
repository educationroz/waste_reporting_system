import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .ws_limits import ConnectionLimitMixin


class WasteRequestConsumer(ConnectionLimitMixin, AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time waste request updates.
    Connect: ws://localhost:8000/ws/requests/
    Broadcasts status changes to all connected clients in 'request_updates' group.
    """

    GROUP_NAME = 'request_updates'

    async def connect(self):
        # Handshake churn check runs BEFORE auth: rejecting an anonymous flood
        # must be cheaper than the session lookup it would otherwise trigger.
        if not await self.enforce_handshake_rate():
            return

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        # Cap concurrent sockets per user. Must run BEFORE group_add so a
        # refused connection never joins the broadcast group.
        if not await self.enforce_connection_limit(user):
            return

        self.user = user
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()
        await self.send(json.dumps({
            'type': 'connection_established',
            'message': f'Connected as {user.username}',
        }))

    async def disconnect(self, close_code):
        await self.release_connection_slot()
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data):
        """
        Handle incoming messages from client.
        Supported types:
          - ping: keepalive
          - request_update: broadcast status change (admin/driver only)
        """
        # Flood protection: one socket spamming frames still costs CPU even
        # though the connection cap is satisfied.
        if not await self.check_message_rate():
            return

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
            result = await self.resolve_request_broadcast(data.get('request_id'))
            if result is None:
                await self.send(json.dumps({'type': 'error', 'message': 'Request not found.'}))
                return
            if result.get('error'):
                await self.send(json.dumps({'type': 'error', 'message': result['error']}))
                return
            await self.channel_layer.group_send(
                self.GROUP_NAME,
                {
                    'type': 'broadcast_request_update',
                    'request_id': result['request_id'],
                    'status': result['status'],
                    'updated_by': result['updated_by'],
                }
            )

    @database_sync_to_async
    def resolve_request_broadcast(self, request_id):
        """Validate that the sender may broadcast about this request.

        The client-supplied 'status' is never trusted: we re-read the row from
        the DB so a driver cannot push a fake "completed" for a request that
        isn't theirs (or that didn't actually change). Admins may broadcast any
        request; drivers only ones assigned to them.
        """
        from .models import WasteRequest
        try:
            req = WasteRequest.objects.select_related('driver', 'driver__user').get(pk=request_id)
        except (WasteRequest.DoesNotExist, ValueError, TypeError):
            return None
        is_admin = self.user.role == 'admin'
        is_assigned_driver = (
            self.user.role == 'driver'
            and req.driver is not None
            and req.driver.user_id == self.user.id
        )
        if not (is_admin or is_assigned_driver):
            return {'error': 'You can only broadcast updates for requests assigned to you.'}
        return {
            'request_id': req.id,
            'status': req.status,
            'updated_by': self.user.username,
            'owner_user_id': req.user_id,
            'driver_user_id': req.driver.user_id if req.driver else None,
        }

    def _may_receive_update(self, event):
        """Scope a broadcast to what this socket's user is entitled to see.

        The REST layer already scopes via get_queryset(); without the same check
        here a citizen's socket would receive zone/driver/waste-type metadata for
        every request in the system. Admins see everything.
        """
        role = getattr(self.user, 'role', None)
        if role == 'admin':
            return True

        # Absence of ownership info means the sender already authorised the
        # broadcast against a row this user is party to (driver self-broadcast).
        if 'owner_user_id' not in event:
            return role in ('driver', 'admin')

        if role == 'driver':
            return event.get('driver_user_id') == self.user.id
        return event.get('owner_user_id') == self.user.id

    async def broadcast_request_update(self, event):
        """Called when group_send fires 'broadcast_request_update'."""
        if not self._may_receive_update(event):
            return
        await self.send(json.dumps({
            'type': 'request_update',
            'request_id': event['request_id'],
            'status': event['status'],
            'status_display': event.get('status_display'),
            'waste_type': event.get('waste_type'),
            'waste_type_display': event.get('waste_type_display'),
            'zone': event.get('zone', ''),
            'driver_name': event.get('driver_name', ''),
            'updated_by': event['updated_by'],
        }))


class DriverLocationConsumer(ConnectionLimitMixin, AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time driver GPS location tracking.
    Connect: ws://localhost:8000/ws/driver-locations/
    """

    GROUP_NAME = 'driver_locations'

    async def connect(self):
        # Handshake churn check runs BEFORE auth: rejecting an anonymous flood
        # must be cheaper than the session lookup it would otherwise trigger.
        if not await self.enforce_handshake_rate():
            return

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        # Live driver GPS is an admin/citizen boundary: a logged-in citizen must
        # not be able to subscribe and read every driver's position. Drivers are
        # allowed in because this same socket is the WRITE path for their own
        # GPS (see receive()); they are filtered down to their own location in
        # driver_location_update() rather than being denied outright.
        if getattr(user, 'role', None) not in ('admin', 'driver'):
            await self.close(code=4003)
            return

        # Cap concurrent sockets per user. Must run BEFORE group_add so a
        # refused connection never joins the broadcast group.
        if not await self.enforce_connection_limit(user):
            return

        self.user = user
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.release_connection_slot()
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data):
        """Driver sends their GPS coordinates."""
        if not await self.check_message_rate():
            return

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

        # Reject junk/out-of-range coordinates before they touch the DB — a
        # malicious or buggy socket could otherwise store nan/infinite/absurd
        # values that corrupt the admin map (same guard as update_location).
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            return
        if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
            return
        lat_f = round(lat_f, 6)
        lng_f = round(lng_f, 6)

        # Save to DB and get driver details
        driver_info = await self.save_driver_location(lat_f, lng_f)
        
        if driver_info:
            # Broadcast to the group; delivery is filtered per-socket in
            # driver_location_update() so a driver only ever receives their own
            # position while admins receive everyone's.
            await self.channel_layer.group_send(
                self.GROUP_NAME,
                {
                    'type': 'driver_location_update',
                    'driver_id': driver_info['id'],
                    'driver_user_id': driver_info['driver_user_id'],
                    'driver_name': driver_info['driver_name'],
                    'latitude': str(lat_f),
                    'longitude': str(lng_f),
                    'vehicle_plate': driver_info.get('vehicle_plate'),
                    'is_available': driver_info.get('is_available', True),
                }
            )

    async def driver_location_update(self, event):
        # Admins watch the whole fleet; a driver may only see their own position.
        if getattr(self.user, 'role', None) != 'admin':
            if event.get('driver_user_id') != self.user.id:
                return
        # Only send necessary location data - no personal contact info
        await self.send(json.dumps({
            'type': 'driver_location',
            'driver_id': event.get('driver_id'),
            'driver_name': event.get('driver_name') or f"Driver #{event.get('driver_id', '')}",
            'latitude': str(event.get('latitude', '')),
            'longitude': str(event.get('longitude', '')),
            'vehicle_plate': event.get('vehicle_plate') or '',
            'is_available': event.get('is_available', True),
        }))

    async def route_update(self, event):
        """Handle optimized route updates and broadcast to connected clients.

        Admins see every generated route; a driver only receives their own,
        otherwise every driver on the socket would be handed another driver's
        stop list.
        """
        if getattr(self.user, 'role', None) != 'admin':
            if event.get('driver_user_id') != self.user.id:
                return
        await self.send(json.dumps({
            'type': 'route_update',
            'driver_id': event['driver_id'],
            'route_id': event['route_id'],
            'waypoints': event['waypoints'],
            'total_distance': event['total_distance'],
            'total_stops': event['total_stops'],
        }))

    @database_sync_to_async
    def save_driver_location(self, lat, lng):
        from .models import Driver
        try:
            driver = Driver.objects.select_related('vehicle').get(user=self.user)
            driver.current_latitude = lat
            driver.current_longitude = lng
            driver.save(update_fields=['current_latitude', 'current_longitude'])
            return {
                'id': driver.id,
                'driver_user_id': driver.user_id,
                'driver_name': self.user.username,
                'vehicle_plate': driver.vehicle.plate_number if driver.vehicle else None,
                'is_available': driver.is_available,
            }
        except Driver.DoesNotExist:
            return None  # Silent fail - driver profile not created yet

class NotificationConsumer(ConnectionLimitMixin, AsyncWebsocketConsumer):
    """
    Personal notification channel per user.
    Connect: ws://localhost:8000/ws/notifications/
    """

    async def connect(self):
        # Handshake churn check runs BEFORE auth: rejecting an anonymous flood
        # must be cheaper than the session lookup it would otherwise trigger.
        if not await self.enforce_handshake_rate():
            return

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        if not await self.enforce_connection_limit(user):
            return

        self.user = user
        self.group_name = f'notifications_user_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.release_connection_slot()
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass  # Users only receive notifications, not send

    async def send_notification(self, event):
        """Called by group_send to push notification to user's socket."""
        await self.send(json.dumps({
            'type': 'notification',
            'id': event.get('id'),
            'title': event['title'],
            'message': event['message'],
            'notification_type': event['notification_type'],
            'created_at': event.get('created_at', ''),
        }))


class ComplaintConsumer(ConnectionLimitMixin, AsyncWebsocketConsumer):
    """
    Real-time complaint updates.
    Connect: ws://localhost:8000/ws/complaints/
    Broadcasts complaint create/status/delete changes to the
    'complaint_updates' group so open tables refresh live.

    Admins monitor every complaint; a complainant connecting to their own
    /complaints/ page is filtered down to the rows they filed (see
    complaint_update()). Denying non-admins at connect() was wrong: the citizen
    page uses this same socket, so its live status updates could never work.
    """

    GROUP_NAME = 'complaint_updates'

    async def connect(self):
        if not await self.enforce_handshake_rate():
            return

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        if not await self.enforce_connection_limit(user):
            return

        self.user = user
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.release_connection_slot()
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data):
        # Read-only socket: clients never publish complaint changes. A
        # non-dict/non-JSON frame is ignored rather than echoing an error back.
        return

    async def complaint_update(self, event):
        """Called by group_send to push a complaint change to the client."""
        if getattr(self.user, 'role', None) != 'admin':
            if event.get('owner_user_id') != self.user.id:
                return
        await self.send(json.dumps({
            'type': 'complaint_update',
            'complaint_id': event['complaint_id'],
            'status': event.get('status'),
            'status_display': event.get('status_display'),
            'deleted': bool(event.get('deleted', False)),
        }))