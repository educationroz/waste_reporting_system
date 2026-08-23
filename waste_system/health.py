"""
Health-check endpoints for load balancers and container orchestrators.

Two endpoints are exposed (wired up in ``waste_system/urls.py``):

``/healthz/live``  — *liveness*. Answers one question: "is this process still
                     able to serve a request?" It touches no dependency, so a
                     Redis outage never makes an orchestrator kill an otherwise
                     healthy container. Always 200 unless the worker is wedged.

``/healthz``       — *readiness*. Probes the things a request actually needs:
                     the database, the Django cache, and the Channels layer
                     (plus a direct Redis PING when Redis is configured).
                     Returns 200 when every required dependency answers and
                     503 when one does not, which is the signal a load balancer
                     uses to pull the instance out of rotation.

Both return JSON and are unauthenticated on purpose — probes come from an LB or
kubelet that has no session. Nothing sensitive is leaked: failure details are
exception *types* and short messages, never credentials or DSNs. Set
``HEALTHCHECK_DETAIL=False`` in the environment to redact even those.

Notes for whoever deploys this:
  * ``SECURE_SSL_REDIRECT`` is on in production, so both paths are listed in
    ``SECURE_REDIRECT_EXEMPT`` — otherwise a plain-HTTP probe would get a 301
    and be scored as "down".
  * Probes that hit the instance by IP send a Host header that is usually not
    in ``ALLOWED_HOSTS``, which makes Django answer 400. Either add the probe's
    Host value to ``ALLOWED_HOSTS`` or configure the probe to send a real one.
"""

import asyncio
import time
from functools import wraps

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# How long any single dependency probe may take before it is called a failure.
# Keep this comfortably below the probe timeout configured on the LB, otherwise
# the LB gives up first and every check looks like a timeout.
HEALTHCHECK_TIMEOUT = float(getattr(settings, 'HEALTHCHECK_TIMEOUT', 2.0))

# Include exception messages in the JSON body. Handy while debugging a bad
# deploy; turn it off if the endpoint is reachable from outside the cluster.
HEALTHCHECK_DETAIL = bool(getattr(settings, 'HEALTHCHECK_DETAIL', True))

# Status vocabulary. "skipped" means the dependency is not part of this
# deployment (e.g. Redis when USE_REDIS is off) and must NOT fail the probe.
OK = 'ok'
FAILED = 'failed'
SKIPPED = 'skipped'


def _elapsed_ms(start):
    return round((time.monotonic() - start) * 1000, 2)


def _error_detail(exc):
    """Render an exception for the JSON body, honouring HEALTHCHECK_DETAIL."""
    if not HEALTHCHECK_DETAIL:
        return type(exc).__name__
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    # One line, bounded length: probe output ends up in LB logs.
    message = ' '.join(message.split())[:200]
    return f'{type(exc).__name__}: {message}'


def check(name):
    """
    Wrap a probe so it can never raise and always reports its own duration.

    A health endpoint that 500s is worse than useless — the orchestrator
    can't tell "the app is broken" from "the health check is broken" — so
    every probe result is normalised into the same dict shape here.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = func(*args, **kwargs) or {}
                result.setdefault('status', OK)
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                result = {'status': FAILED, 'error': _error_detail(exc)}
            result['duration_ms'] = _elapsed_ms(start)
            result['name'] = name
            return result
        return wrapper
    return decorator


# ─── Individual probes ────────────────────────────────────────────────────────

@check('database')
def check_database(alias='default'):
    """
    Round-trip a trivial query on the real connection.

    ``SELECT 1`` rather than an ORM call on purpose: it needs no tables, so the
    check keeps working on a fresh database and cannot be broken by a migration
    that is mid-flight.
    """
    connection = connections[alias]
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        row = cursor.fetchone()
    if not row or row[0] != 1:
        raise RuntimeError(f'unexpected result from SELECT 1: {row!r}')
    return {
        'engine': connection.settings_dict.get('ENGINE', '').rsplit('.', 1)[-1],
        'name': 'database',
    }


@check('cache')
def check_cache():
    """
    Write, read back and delete one key.

    With the default LocMemCache this only proves the process is sane, but it
    becomes a real dependency check the moment the cache is pointed at Redis or
    Memcached, so it is worth having wired up in advance.
    """
    key = f'healthz:{time.monotonic_ns()}'
    cache.set(key, 'ok', 10)
    value = cache.get(key)
    cache.delete(key)
    if value != 'ok':
        raise RuntimeError(f'cache round-trip returned {value!r}')
    backend = settings.CACHES.get('default', {}).get('BACKEND', 'unknown')
    return {'backend': backend.rsplit('.', 1)[-1]}


async def _channel_layer_roundtrip(layer, timeout):
    """Send a message to a private channel and read it back."""
    channel_name = await layer.new_channel()
    await asyncio.wait_for(
        layer.send(channel_name, {'type': 'healthz.ping'}),
        timeout,
    )
    return await asyncio.wait_for(layer.receive(channel_name), timeout)


@check('channels')
def check_channel_layer():
    """
    Prove the Channels layer can carry a message end to end.

    This is the check that actually matters for the WebSocket features (live
    driver locations, notifications): a layer that cannot deliver a message
    means those silently stop working while plain HTTP still looks fine.

    A round-trip on a throwaway channel is used rather than merely importing
    the backend, because with the Redis backend it exercises the real TCP
    connection, auth and BZPOPMIN support.
    """
    # Imported lazily so this module stays importable if channels is absent.
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError('no channel layer configured (CHANNEL_LAYERS is empty)')

    backend = settings.CHANNEL_LAYERS.get('default', {}).get('BACKEND', 'unknown')
    in_memory = 'InMemory' in backend

    message = async_to_sync(_channel_layer_roundtrip)(layer, HEALTHCHECK_TIMEOUT)
    if not message or message.get('type') != 'healthz.ping':
        raise RuntimeError(f'channel layer returned {message!r}')

    result = {'backend': backend.rsplit('.', 1)[-1]}
    if in_memory:
        # Not a failure — it is the documented dev fallback — but it is worth
        # surfacing, because behind a load balancer each instance would then
        # have its own isolated layer and cross-instance fan-out would break.
        result['note'] = (
            'in-memory layer: messages do not cross processes, '
            'set USE_REDIS=True for multi-instance deployments'
        )
    return result


@check('redis')
def check_redis():
    """
    PING Redis directly, using the same connection settings as the layer.

    Skipped (and therefore *not* a failure) when ``USE_REDIS`` is off, since a
    single-instance dev or small deployment legitimately runs without it. Note
    that settings.py silently flips ``USE_REDIS`` off when ``channels_redis``
    is not importable, so this check reports "skipped" in that case too — the
    channels probe above is what tells you whether messaging actually works.
    """
    if not getattr(settings, 'USE_REDIS', False):
        return {
            'status': SKIPPED,
            'note': 'USE_REDIS is off; Channels uses the in-memory layer',
        }

    import redis  # provided by channels-redis

    # redis-py 5+ retries a failed connect three times with backoff by
    # default, so a refused connection takes ~3x socket_connect_timeout to
    # report — measured at 6s against a 2s timeout. A health probe must fail
    # fast and predictably, so retries are switched off and the connect
    # timeout becomes the real upper bound.
    client_kwargs = {
        'host': settings.REDIS_HOST,
        'port': settings.REDIS_PORT,
        'password': settings.REDIS_PASSWORD or None,
        'socket_connect_timeout': HEALTHCHECK_TIMEOUT,
        'socket_timeout': HEALTHCHECK_TIMEOUT,
    }
    try:
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        client_kwargs['retry'] = Retry(NoBackoff(), 0)
        client_kwargs['retry_on_error'] = []
    except ImportError:
        # Older redis-py without the retry API: nothing to disable.
        pass

    client = redis.Redis(**client_kwargs)
    try:
        if not client.ping():
            raise RuntimeError('PING returned a falsy response')
        return {'host': f'{settings.REDIS_HOST}:{settings.REDIS_PORT}'}
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - never let cleanup fail the probe
            pass


# Order matters only for readability of the JSON body.
READINESS_CHECKS = (
    check_database,
    check_cache,
    check_channel_layer,
    check_redis,
)


def _run_checks():
    results = {}
    healthy = True
    for probe in READINESS_CHECKS:
        result = probe()
        name = result.pop('name')
        results[name] = result
        if result['status'] == FAILED:
            healthy = False
    return healthy, results


# ─── Views ────────────────────────────────────────────────────────────────────

@csrf_exempt
@never_cache
@require_http_methods(['GET', 'HEAD'])
def healthz(request):
    """
    Readiness probe: 200 when every dependency answers, 503 when one does not.

    The 503 is the whole point — it is what makes a load balancer stop sending
    traffic to an instance whose database or Redis has gone away, instead of
    letting it serve 500s to real users.
    """
    start = time.monotonic()
    healthy, checks = _run_checks()
    payload = {
        'status': OK if healthy else FAILED,
        'timestamp': timezone.now().isoformat(),
        'duration_ms': _elapsed_ms(start),
        'checks': checks,
    }
    response = JsonResponse(payload, status=200 if healthy else 503)
    # Belt and braces on top of @never_cache: some proxies cache 200s from
    # unknown endpoints, which would freeze a stale "ok" in front of a dead app.
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


@csrf_exempt
@never_cache
@require_http_methods(['GET', 'HEAD'])
def healthz_live(request):
    """
    Liveness probe: 200 as long as this process can run a view.

    Deliberately dependency-free. Wiring a Kubernetes livenessProbe to the full
    readiness check is a classic way to turn a brief Redis blip into a
    cluster-wide restart loop.
    """
    response = JsonResponse({
        'status': OK,
        'timestamp': timezone.now().isoformat(),
    })
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response
