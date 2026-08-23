"""Tests for the WebSocket connection/handshake/message limits.

These cover the three limits in ``api_app/ws_limits.py``. Each one exists
because a real gap was measured against the running code, so each test asserts
the *specific* failure mode rather than just "a limit exists":

* the connection cap does nothing against connect/disconnect churn,
* nothing at all rate-limited anonymous handshakes,
* one socket can still flood ``receive()`` while respecting both of the above.
"""

import json

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase, override_settings

from . import ws_limits
from .consumers import DriverLocationConsumer, NotificationConsumer

User = get_user_model()


def make_communicator(consumer_cls, user, path, ip='203.0.113.7'):
    """A communicator with a predictable client IP.

    The handshake limit keys on X-Forwarded-For (falling back to scope
    ['client']), so tests must set it explicitly or every test shares one
    bucket and they interfere with each other.
    """
    communicator = WebsocketCommunicator(consumer_cls.as_asgi(), path)
    communicator.scope['user'] = user
    communicator.scope['client'] = (ip, 12345)
    communicator.scope['headers'] = [(b'x-forwarded-for', ip.encode())]
    return communicator


class WebSocketConnectionCapTests(TransactionTestCase):
    """Per-user cap on CONCURRENT sockets (close code 4008)."""

    def setUp(self):
        ws_limits.reset_all_counts()

    def tearDown(self):
        ws_limits.reset_all_counts()

    async def _user(self, username='capuser'):
        return await sync_to_async(User.objects.create_user)(
            username=username, password='pw', email=f'{username}@example.com'
        )

    async def test_sockets_up_to_the_cap_are_accepted(self):
        user = await self._user()
        communicators = []

        with override_settings(WS_MAX_CONNECTIONS_PER_USER=5):
            for _ in range(5):
                c = make_communicator(NotificationConsumer, user, '/ws/notifications/')
                connected, _ = await c.connect()
                self.assertTrue(connected)
                communicators.append(c)

            self.assertEqual(
                ws_limits.current_connection_count(NotificationConsumer, user.id), 5
            )

        for c in communicators:
            await c.disconnect()

    async def test_socket_over_the_cap_is_refused_with_4008(self):
        user = await self._user()
        communicators = []

        with override_settings(WS_MAX_CONNECTIONS_PER_USER=2):
            for _ in range(2):
                c = make_communicator(NotificationConsumer, user, '/ws/notifications/')
                await c.connect()
                communicators.append(c)

            extra = make_communicator(NotificationConsumer, user, '/ws/notifications/')
            connected, code = await extra.connect()

            self.assertFalse(connected)
            self.assertEqual(code, ws_limits.WS_CLOSE_TOO_MANY_CONNECTIONS)
            await extra.disconnect()

        for c in communicators:
            await c.disconnect()

    async def test_slot_is_released_on_disconnect(self):
        """A closed socket must free its slot, or users lock themselves out."""
        user = await self._user()

        with override_settings(WS_MAX_CONNECTIONS_PER_USER=1):
            first = make_communicator(NotificationConsumer, user, '/ws/notifications/')
            connected, _ = await first.connect()
            self.assertTrue(connected)
            await first.disconnect()

            second = make_communicator(NotificationConsumer, user, '/ws/notifications/')
            connected, _ = await second.connect()
            self.assertTrue(connected, 'slot was not released on disconnect')
            await second.disconnect()

        self.assertEqual(
            ws_limits.current_connection_count(NotificationConsumer, user.id), 0
        )

    async def test_cap_is_per_user_not_global(self):
        one = await self._user('capuser_a')
        two = await self._user('capuser_b')

        with override_settings(WS_MAX_CONNECTIONS_PER_USER=1):
            a = make_communicator(NotificationConsumer, one, '/ws/notifications/')
            await a.connect()

            b = make_communicator(NotificationConsumer, two, '/ws/notifications/')
            connected, _ = await b.connect()
            self.assertTrue(connected, 'one user exhausted another user budget')

            await a.disconnect()
            await b.disconnect()


class WebSocketHandshakeRateTests(TransactionTestCase):
    """Per-IP handshake limit (close code 4010), checked BEFORE auth."""

    def setUp(self):
        ws_limits.reset_all_counts()

    def tearDown(self):
        ws_limits.reset_all_counts()

    async def test_connect_disconnect_churn_is_capped(self):
        """The connection cap alone never fires here: each disconnect frees
        the slot, so without a handshake limit this loop runs forever."""
        user = await sync_to_async(User.objects.create_user)(
            username='churner', password='pw', email='churn@example.com'
        )
        accepted = 0
        refused_codes = set()

        with override_settings(
            WS_MAX_HANDSHAKES_PER_WINDOW=10, WS_HANDSHAKE_WINDOW_SECONDS=60
        ):
            for _ in range(25):
                c = make_communicator(NotificationConsumer, user, '/ws/notifications/')
                connected, code = await c.connect()
                if connected:
                    accepted += 1
                else:
                    refused_codes.add(code)
                await c.disconnect()

        self.assertEqual(accepted, 10)
        self.assertEqual(refused_codes, {ws_limits.WS_CLOSE_HANDSHAKE_FLOOD})

    async def test_anonymous_flood_is_capped(self):
        """Anonymous sockets are rejected at 4001, but that still costs a
        session lookup — so they must hit the handshake limit too."""
        codes = []

        with override_settings(
            WS_MAX_HANDSHAKES_PER_WINDOW=5, WS_HANDSHAKE_WINDOW_SECONDS=60
        ):
            for _ in range(12):
                c = make_communicator(
                    NotificationConsumer, AnonymousUser(), '/ws/notifications/'
                )
                _, code = await c.connect()
                codes.append(code)
                await c.disconnect()

        self.assertEqual(codes[:5], [4001] * 5, 'auth rejection should come first')
        self.assertEqual(codes[5:], [ws_limits.WS_CLOSE_HANDSHAKE_FLOOD] * 7)

    async def test_limit_is_per_ip(self):
        user = await sync_to_async(User.objects.create_user)(
            username='ipuser', password='pw', email='ip@example.com'
        )

        with override_settings(
            WS_MAX_HANDSHAKES_PER_WINDOW=3, WS_HANDSHAKE_WINDOW_SECONDS=60
        ):
            for _ in range(4):
                c = make_communicator(
                    NotificationConsumer, user, '/ws/notifications/', ip='198.51.100.1'
                )
                await c.connect()
                await c.disconnect()

            other = make_communicator(
                NotificationConsumer, user, '/ws/notifications/', ip='198.51.100.99'
            )
            connected, _ = await other.connect()
            self.assertTrue(connected, 'one IP exhausted another IP budget')
            await other.disconnect()

    async def test_zero_disables_the_limit(self):
        user = await sync_to_async(User.objects.create_user)(
            username='nolimit', password='pw', email='n@example.com'
        )
        accepted = 0

        with override_settings(WS_MAX_HANDSHAKES_PER_WINDOW=0):
            for _ in range(30):
                c = make_communicator(NotificationConsumer, user, '/ws/notifications/')
                connected, _ = await c.connect()
                if connected:
                    accepted += 1
                await c.disconnect()

        self.assertEqual(accepted, 30)


class ClientIPResolutionTests(TransactionTestCase):
    """X-Forwarded-For must win over the proxy's own address.

    Behind a load balancer scope['client'] is the balancer for every visitor,
    which would turn the per-IP limit into a global one and lock out the site.
    """

    def test_uses_first_forwarded_for_entry(self):
        scope = {
            'headers': [(b'x-forwarded-for', b'9.9.9.9, 10.0.0.1')],
            'client': ('10.0.0.1', 1),
        }
        self.assertEqual(ws_limits._client_ip(scope), '9.9.9.9')

    def test_falls_back_to_scope_client(self):
        scope = {'headers': [], 'client': ('7.7.7.7', 1)}
        self.assertEqual(ws_limits._client_ip(scope), '7.7.7.7')

    def test_handles_missing_client(self):
        self.assertEqual(ws_limits._client_ip({'headers': []}), 'unknown')


class WebSocketMessageRateTests(TransactionTestCase):
    """Per-socket inbound message limit (close code 4009)."""

    def setUp(self):
        ws_limits.reset_all_counts()

    def tearDown(self):
        ws_limits.reset_all_counts()

    async def test_message_flood_closes_socket_with_4009(self):
        driver = await sync_to_async(User.objects.create_user)(
            username='floodrv', password='pw', email='f@example.com', role='driver'
        )

        with override_settings(WS_MAX_MESSAGES_PER_WINDOW=5):
            c = make_communicator(
                DriverLocationConsumer, driver, '/ws/driver-locations/'
            )
            connected, _ = await c.connect()
            self.assertTrue(connected)

            close_code = None
            for _ in range(12):
                await c.send_to(
                    text_data=json.dumps({'latitude': 28.2, 'longitude': 83.9})
                )
                try:
                    output = await c.receive_output(timeout=0.4)
                except Exception:
                    continue
                if output['type'] == 'websocket.close':
                    close_code = output.get('code')
                    break

            self.assertEqual(close_code, ws_limits.WS_CLOSE_MESSAGE_FLOOD)
            await c.disconnect()


class WebSocketAuthTests(TransactionTestCase):
    """Anonymous handshakes are rejected on every socket (close code 4001)."""

    def setUp(self):
        ws_limits.reset_all_counts()

    async def test_anonymous_rejected_on_notifications(self):
        c = make_communicator(
            NotificationConsumer, AnonymousUser(), '/ws/notifications/'
        )
        connected, code = await c.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4001)
        await c.disconnect()

    async def test_anonymous_rejected_on_driver_locations(self):
        c = make_communicator(
            DriverLocationConsumer, AnonymousUser(), '/ws/driver-locations/'
        )
        connected, code = await c.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4001)
        await c.disconnect()

    async def test_refused_anonymous_socket_leaks_no_slot(self):
        c = make_communicator(
            NotificationConsumer, AnonymousUser(), '/ws/notifications/'
        )
        await c.connect()
        await c.disconnect()
        self.assertEqual(
            ws_limits.current_connection_count(NotificationConsumer, None), 0
        )
