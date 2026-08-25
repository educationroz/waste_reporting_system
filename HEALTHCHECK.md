# Health checks

Two endpoints let a load balancer or orchestrator tell a healthy instance from
a broken one, so traffic is routed away from a process whose database or Redis
has gone missing instead of letting it serve 500s to real users.

| Endpoint        | Purpose   | Checks                             | Codes     |
|-----------------|-----------|------------------------------------|-----------|
| `/healthz/live` | liveness  | nothing — just that the worker runs | `200`     |
| `/healthz`      | readiness | database, cache, Channels, Redis    | `200`/`503` |

Both accept `GET` and `HEAD`, need no authentication, are CSRF-exempt, and send
`Cache-Control: no-store`.

## Why two endpoints

Use **`/healthz/live`** for a Kubernetes `livenessProbe` and **`/healthz`** for
a `readinessProbe` / load-balancer health check.

Pointing a liveness probe at the full dependency check is a well-known way to
turn a brief Redis blip into a cluster-wide restart loop: every instance fails
its check at once, every instance gets killed, and nothing is left to serve
traffic once Redis recovers. Liveness answers "should this container be
restarted?", readiness answers "should this container get traffic?" — only the
second one should care about dependencies.

## Response

`200` when everything required answers:

```json
{
  "status": "ok",
  "timestamp": "2026-08-23T11:07:47.304935+00:00",
  "duration_ms": 1.62,
  "checks": {
    "database": {"engine": "sqlite3", "status": "ok", "duration_ms": 0.43},
    "cache":    {"backend": "LocMemCache", "status": "ok", "duration_ms": 0.73},
    "channels": {"backend": "InMemoryChannelLayer", "status": "ok", "duration_ms": 0.41,
                 "note": "in-memory layer: messages do not cross processes, ..."},
    "redis":    {"status": "skipped", "note": "USE_REDIS is off; ..."}
  }
}
```

`503` with the same shape when a dependency fails, so the body still says
*which* one:

```json
{
  "status": "failed",
  "checks": {
    "database": {"engine": "sqlite3", "status": "ok", "duration_ms": 0.47},
    "channels": {"status": "failed", "error": "ConnectionError: Error 111 ...", "duration_ms": 2.75},
    "redis":    {"status": "failed", "error": "ConnectionError: Error 111 ...", "duration_ms": 1.22}
  }
}
```

Every probe runs even after one fails, so a single request shows the full blast
radius rather than only the first problem.

### Statuses

- **`ok`** — the dependency answered.
- **`failed`** — it did not. Fails the endpoint (`503`).
- **`skipped`** — not part of this deployment. Does **not** fail the endpoint.
  Redis reports this when `USE_REDIS` is off, since running without it is a
  legitimate single-instance setup.

## What each check actually does

- **database** — `SELECT 1` on a real cursor. No tables involved, so it works
  on a fresh database and survives a migration in flight.
- **cache** — set / get / delete one key. Mostly a formality with the default
  LocMemCache, but becomes a real check the moment `CACHES` points at Redis.
- **channels** — sends a message to a throwaway channel and reads it back.
  This is the one that matters for live driver locations and notifications: a
  layer that cannot deliver a message breaks those while plain HTTP still looks
  fine. With the Redis backend it exercises the real TCP connection and auth.
- **redis** — a direct `PING` using the same connection settings as the layer,
  which separates "Redis is down" from "the Channels layer is misconfigured".

When the in-memory layer is active the channels check passes but attaches a
`note`. That is intentional — it is the documented dev fallback, not a fault —
but behind a load balancer each instance would have its own isolated layer and
cross-instance fan-out would silently not work. Set `USE_REDIS=True` for any
multi-instance deployment.

## Settings

| Setting / env var     | Default        | Meaning |
|-----------------------|----------------|---------|
| `HEALTHCHECK_TIMEOUT` | `2.0`          | Seconds any single probe may take. Keep it **below** the probe timeout on the LB, or the LB gives up first and every check looks like a timeout. |
| `HEALTHCHECK_DETAIL`  | `DEBUG`        | Include exception messages in the body. Defaults on in development and **off in production**, so a publicly reachable `/healthz` reports only exception types. |

## Deployment notes

**TLS redirects.** `SECURE_SSL_REDIRECT` is on when `DEBUG=False`, so both
paths are listed in `SECURE_REDIRECT_EXEMPT`. Without that, a plain-HTTP probe
from inside the network gets a `301` and every probe implementation scores it
as unhealthy — draining a perfectly healthy instance. The exemption is narrow:
`/admin/` and every other URL still redirect.

**`ALLOWED_HOSTS`.** A probe that hits the instance by IP sends a `Host` header
that is usually not in `ALLOWED_HOSTS`, and Django answers `400` before the
view ever runs. Either add the probe's `Host` value to `ALLOWED_HOSTS` or
configure the probe to send a real hostname. This bites people far more often
than the check itself failing.

### Kubernetes

```yaml
livenessProbe:
  httpGet: {path: /healthz/live, port: 8000, httpHeaders: [{name: Host, value: waste.example.com}]}
  initialDelaySeconds: 10
  periodSeconds: 20
  timeoutSeconds: 3
readinessProbe:
  httpGet: {path: /healthz, port: 8000, httpHeaders: [{name: Host, value: waste.example.com}]}
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5      # must exceed HEALTHCHECK_TIMEOUT
  failureThreshold: 3
```

`failureThreshold: 3` avoids pulling an instance out of rotation over one
slow query.

### nginx / HAProxy

```nginx
location = /healthz     { proxy_pass http://app; access_log off; }
location = /healthz/live { proxy_pass http://app; access_log off; }
```

```
option httpchk GET /healthz
http-check expect status 200
```

## Tests

`waste_system/test_health.py` — 27 tests, mostly failure paths, because an
endpoint that only ever returns 200 is indistinguishable from no health check
at all. They cover: DB down, cache silently losing writes, channel layer
raising or missing, Redis unreachable, a probe raising an unexpected exception
(must still be a clean JSON `503`, never a `500`), detail redaction, method
rejection, and the SSL-redirect exemption.

```bash
python manage.py test waste_system.test_health --settings=waste_system.test_settings
```
