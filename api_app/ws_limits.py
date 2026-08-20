"""Per-user WebSocket connection caps and message rate limiting.

WHY THIS EXISTS
---------------
DRF's throttles (``AnonRateThrottle``/``UserRateThrottle``) only run inside the
HTTP request/response cycle. WebSockets never touch that code path, so before
this module the three consumers in ``api_app/consumers.py`` would authenticate a
user and then ``accept()`` an unbounded number of sockets.

That is a cheap resource-exhaustion vector: one authenticated account (or one
stolen session cookie) could open thousands of sockets from a loop, and each one
costs a channel-layer group membership, an event loop task, and — under
``channels_redis`` — a Redis subscription. The browser client in ``base.html``
does use exponential backoff, but a *cooperative* client is not a control: an
attacker just calls ``new WebSocket()`` in a loop.

TWO INDEPENDENT LIMITS
----------------------
1. **Connection cap** (``MAX_CONNECTIONS_PER_USER``) — how many sockets one user
   may hold open at once, counted per consumer class so a chatty dashboard
   cannot starve notifications. Exceeding it closes the *new* socket with code
   4008; existing sockets are left alone.

2. **Message rate limit** (``MAX_MESSAGES_PER_WINDOW`` in
   ``MESSAGE_WINDOW_SECONDS``) — a sliding window over inbound frames. A socket
   that floods gets closed with 4009. Without this, a single connection can
   still burn CPU by spamming ``receive()``.

WHY AN IN-PROCESS REGISTRY
--------------------------
The counter lives in a module-level dict guarded by an ``asyncio.Lock``, so it
is per-process. With multiple workers a user's effective ceiling is
``workers × MAX_CONNECTIONS_PER_USER``.

That is a deliberate trade. The alternative — a Redis INCR/DECR — turns every
handshake into a network round-trip and needs careful cleanup for sockets lost
to a hard crash (no ``disconnect``), or the counter leaks upward and eventually
locks the user out of their own account. A per-process cap has no such failure
mode: if the process dies, its counters die with it. It still converts
"unbounded" into a small constant, which is the actual goal.

For a hard global ceiling, put ``limit_conn`` on the nginx/ingress WebSocket
location — that is the right layer for cross-process limits.

TUNING
------
Override in settings.py (all optional)::

    WS_MAX_CONNECTIONS_PER_USER = 5
    WS_MAX_MESSAGES_PER_WINDOW = 60
    WS_MESSAGE_WINDOW_SECONDS = 10
    WS_EXEMPT_STAFF = False
"""

import asyncio
import time
from collections import defaultdict, deque

from django.conf import settings

# Close codes in the 4000-4999 range are application-defined.
WS_CLOSE_TOO_MANY_CONNECTIONS = 4008
WS_CLOSE_MESSAGE_FLOOD = 4009

# Defaults chosen to sit well above real usage. A normal browser session holds
# one notification socket plus at most one page-specific socket; 5 leaves room
# for several tabs and a reconnect that races its own teardown.
DEFAULT_MAX_CONNECTIONS_PER_USER = 5
DEFAULT_MAX_MESSAGES_PER_WINDOW = 60
DEFAULT_MESSAGE_WINDOW_SECONDS = 10

# {consumer_class_name: {user_id: int}}
_connection_counts = defaultdict(lambda: defaultdict(int))
_counts_lock = asyncio.Lock()


def _setting(name, default):
    return getattr(settings, name, default)


async def _acquire_slot(bucket, user_id, limit):
    """Reserve a connection slot. Returns True if the socket may proceed."""
    async with _counts_lock:
        current = _connection_counts[bucket][user_id]
        if current >= limit:
            return False
        _connection_counts[bucket][user_id] = current + 1
        return True


async def _release_slot(bucket, user_id):
    async with _counts_lock:
        remaining = _connection_counts[bucket][user_id] - 1
        if remaining > 0:
            _connection_counts[bucket][user_id] = remaining
        else:
            # Drop the key entirely so the dict cannot grow without bound as
            # users come and go.
            _connection_counts[bucket].pop(user_id, None)


def current_connection_count(consumer_cls, user_id):
    """Introspection helper for tests and health checks."""
    return _connection_counts[consumer_cls.__name__].get(user_id, 0)


def reset_all_counts():
    """Test helper — clears every bucket."""
    _connection_counts.clear()


class ConnectionLimitMixin:
    """Adds a per-user connection cap and inbound message rate limit.

    Usage: list it *before* ``AsyncWebsocketConsumer`` in the bases, then call
    ``await self.enforce_connection_limit()`` after authenticating and
    ``await self.release_connection_slot()`` in ``disconnect``.
    """

    MAX_CONNECTIONS_PER_USER = None      # None → fall back to settings
    MAX_MESSAGES_PER_WINDOW = None
    MESSAGE_WINDOW_SECONDS = None

    @property
    def _conn_limit(self):
        return self.MAX_CONNECTIONS_PER_USER or _setting(
            'WS_MAX_CONNECTIONS_PER_USER', DEFAULT_MAX_CONNECTIONS_PER_USER
        )

    @property
    def _msg_limit(self):
        return self.MAX_MESSAGES_PER_WINDOW or _setting(
            'WS_MAX_MESSAGES_PER_WINDOW', DEFAULT_MAX_MESSAGES_PER_WINDOW
        )

    @property
    def _msg_window(self):
        return self.MESSAGE_WINDOW_SECONDS or _setting(
            'WS_MESSAGE_WINDOW_SECONDS', DEFAULT_MESSAGE_WINDOW_SECONDS
        )

    async def enforce_connection_limit(self, user):
        """Reserve a slot for ``user``.

        Returns True when the caller may ``accept()``. On refusal the socket has
        already been closed with 4008 and the caller must return immediately.
        """
        # Staff can be exempted for ops dashboards that legitimately hold many
        # sockets. Off by default — an admin session is the most valuable one to
        # steal, so it should be capped too unless you opt out.
        if _setting('WS_EXEMPT_STAFF', False) and getattr(user, 'is_staff', False):
            self._ws_slot_held = False
            return True

        bucket = type(self).__name__
        granted = await _acquire_slot(bucket, user.id, self._conn_limit)

        if not granted:
            self._ws_slot_held = False
            await self.close(code=WS_CLOSE_TOO_MANY_CONNECTIONS)
            return False

        self._ws_slot_held = True
        self._ws_bucket = bucket
        self._ws_user_id = user.id
        self._ws_message_times = deque()
        return True

    async def release_connection_slot(self):
        """Give the slot back. Safe to call even if no slot was held."""
        if getattr(self, '_ws_slot_held', False):
            self._ws_slot_held = False
            await _release_slot(self._ws_bucket, self._ws_user_id)

    async def check_message_rate(self):
        """Sliding-window rate check for one inbound frame.

        Returns True if the frame may be handled. On refusal the socket has been
        closed with 4009.
        """
        times = getattr(self, '_ws_message_times', None)
        if times is None:
            times = self._ws_message_times = deque()

        now = time.monotonic()
        window = self._msg_window
        while times and now - times[0] > window:
            times.popleft()

        if len(times) >= self._msg_limit:
            await self.close(code=WS_CLOSE_MESSAGE_FLOOD)
            return False

        times.append(now)
        return True
