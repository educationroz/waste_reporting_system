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

THREE INDEPENDENT LIMITS
------------------------
1. **Handshake rate** (``WS_MAX_HANDSHAKES_PER_WINDOW`` per client IP) — checked
   *before* authentication, closes with 4010. This is the one the other two
   cannot cover: a concurrency cap does nothing against connect/disconnect in a
   loop, because each disconnect frees the slot immediately. It is also the only
   limit that applies to **anonymous** sockets, which are rejected at 4001 but
   still cost a session lookup and a DB hit each time.

2. **Connection cap** (``MAX_CONNECTIONS_PER_USER``) — how many sockets one user
   may hold open at once, counted per consumer class so a chatty dashboard
   cannot starve notifications. Exceeding it closes the *new* socket with code
   4008; existing sockets are left alone.

3. **Message rate limit** (``MAX_MESSAGES_PER_WINDOW`` in
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
    WS_MAX_HANDSHAKES_PER_WINDOW = 30   # 0 disables the handshake limit
    WS_HANDSHAKE_WINDOW_SECONDS = 60
    WS_EXEMPT_STAFF = False

Note the handshake limit is keyed by **IP**, not user, because it must work
before we know who the user is. Shared-NAT clients (an office, a campus) share
that budget, so keep it generous.
"""

import asyncio
import time
from collections import defaultdict, deque

from django.conf import settings

# Close codes in the 4000-4999 range are application-defined.
WS_CLOSE_TOO_MANY_CONNECTIONS = 4008
WS_CLOSE_MESSAGE_FLOOD = 4009
WS_CLOSE_HANDSHAKE_FLOOD = 4010

# Defaults chosen to sit well above real usage. A normal browser session holds
# one notification socket plus at most one page-specific socket; 5 leaves room
# for several tabs and a reconnect that races its own teardown.
DEFAULT_MAX_CONNECTIONS_PER_USER = 5
DEFAULT_MAX_MESSAGES_PER_WINDOW = 60
DEFAULT_MESSAGE_WINDOW_SECONDS = 10

# Handshake churn. The concurrency cap above only limits how many sockets are
# open AT ONCE — it does nothing against connect/disconnect in a loop, because
# every disconnect frees the slot again. 30 handshakes/60s per IP is well above
# a real client (which opens ~2 sockets per page load and backs off on failure)
# but stops a spin loop.
DEFAULT_MAX_HANDSHAKES_PER_WINDOW = 30
DEFAULT_HANDSHAKE_WINDOW_SECONDS = 60

# {consumer_class_name: {user_id: int}}
_connection_counts = defaultdict(lambda: defaultdict(int))
_counts_lock = asyncio.Lock()

# {client_ip: deque[timestamp]} — shared across consumer classes on purpose:
# the cost being limited is the handshake itself (session lookup + DB hit),
# not membership of any one group.
_handshake_times = defaultdict(deque)
_handshake_lock = asyncio.Lock()


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


def _client_ip(scope):
    """Best-effort client IP from the ASGI scope.

    Behind a proxy the real address is in X-Forwarded-For; scope['client'] would
    otherwise be the load balancer for every visitor, turning a per-IP limit
    into a global one that locks out the whole site.
    """
    for name, value in scope.get('headers') or []:
        if name == b'x-forwarded-for':
            first = value.decode('latin-1').split(',')[0].strip()
            if first:
                return first
    client = scope.get('client')
    return client[0] if client else 'unknown'


async def check_handshake_rate(scope):
    """Sliding-window limit on handshakes per client IP.

    Returns True if this handshake may proceed. Call BEFORE authenticating so
    unauthenticated spam is cheap to reject.
    """
    limit = _setting('WS_MAX_HANDSHAKES_PER_WINDOW', DEFAULT_MAX_HANDSHAKES_PER_WINDOW)
    window = _setting('WS_HANDSHAKE_WINDOW_SECONDS', DEFAULT_HANDSHAKE_WINDOW_SECONDS)
    if not limit:
        return True

    ip = _client_ip(scope)
    now = time.monotonic()

    async with _handshake_lock:
        times = _handshake_times[ip]
        while times and now - times[0] > window:
            times.popleft()

        if len(times) >= limit:
            return False

        times.append(now)

        # Drop idle IPs so the dict cannot grow without bound.
        if len(_handshake_times) > 10000:
            for key in [k for k, v in _handshake_times.items() if not v]:
                _handshake_times.pop(key, None)

    return True


def current_connection_count(consumer_cls, user_id):
    """Introspection helper for tests and health checks."""
    return _connection_counts[consumer_cls.__name__].get(user_id, 0)


def reset_all_counts():
    """Test helper — clears every bucket."""
    _connection_counts.clear()
    _handshake_times.clear()


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

    async def enforce_handshake_rate(self):
        """Reject handshake churn from one IP.

        Returns True when the socket may continue. On refusal the socket has
        already been closed with 4010 and the caller must return immediately.
        Call this FIRST — before the auth check — so anonymous spam is cheap.
        """
        if await check_handshake_rate(self.scope):
            return True

        await self.close(code=WS_CLOSE_HANDSHAKE_FLOOD)
        return False

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
