# Production Readiness Audit — Safha Sahar Waste Reporting System

Scanned: full repo (`api_app`, `auth_app`, `web_app`, `waste_system`, templates, static). This
covers security, performance, admin control/UX, and new ideas. Items are ranked **High / Medium /
Low** by real-world impact.

---

## What's already solid (don't touch)
- JWT auth with rotation + blacklist, DRF throttling per-endpoint (login, register, password reset)
- `SECURE_HSTS_*`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` all correctly gated on `DEBUG=False`
- DB indexes already present on most hot filter fields (`status`, `is_available`, `created_at`, etc.)
- `select_related` already used in 17 places in `api_app/views.py`
- File upload size caps, PDF-only license validation, per-photo size limits
- Activity/audit logging (`AdminLog`) and soft-delete (Recycle Bin) already implemented

---

**Security status:** items 1, 2, 3 and 6 are **resolved** (commits `45cf897`, `bccac33`,
`4392e80`+`c41287d`, `45c4b23`). Items 4 and 5 remain open — see the notes on each.

## 🔴 High priority — Security

1. ~~**JWT stored in `localStorage`** (used in 29 places across templates). Any XSS bug lets an
   attacker steal the token directly (no `HttpOnly` protection).~~
   **RESOLVED** in `45cf897`. Browser auth moved to `HttpOnly` session cookies; fetch calls now send
   `credentials: "same-origin"` + `X-CSRFToken`. Zero `localStorage` token reads remain in templates.
   See `SECURITY-auth-hardening.md`.
2. ~~**WebSocket auth token passed as a URL query param** (`?token=...`) in `consumers.py`/JS. Query
   strings land in server access logs, browser history, and referrer headers.~~
   **RESOLVED** in `bccac33`. Query-string auth removed entirely — the handshake authenticates from
   the session cookie, so no credential touches the URL. Verified: `?token=<jwt>` and anonymous
   handshakes are both rejected on all three sockets.
3. ~~**No `Content-Security-Policy` header** anywhere. You're loading Bootstrap, Leaflet, Google
   Translate, and htmx from multiple CDNs — a CSP would contain damage from any injected script.~~
   **RESOLVED** in `4392e80` + `c41287d`. Two corrections to the finding: it was written against
   `main` (which has no `security.py`), and Google Translate no longer exists — it was replaced by
   Django's server-side i18n. The real weakness was `'unsafe-inline'` in `script-src`; there is now
   a `CSP_MODE=compat|report|strict` rollout path and all 30 inline `<script>` blocks carry a
   per-request nonce. **Remaining before `strict`:** migrate 166 inline `on*=` attributes to
   `addEventListener`. SRI hashes are documented but not guessed offline. See `SECURITY-csp.md`.
4. **SQLite is still the default DB** (`DB_ENGINE` defaults to `sqlite3`). Fine for dev, but if a
   production `.env` ever forgets to set `DB_ENGINE=postgresql`, you silently get SQLite in prod —
   no concurrent-write safety, no real backup story. Consider failing loudly instead of silently
   defaulting when `DEBUG=False`.
5. **`GOOGLE_OAUTH_CLIENT_ID = config('GOOGLE_OAUTH_CLIENT_ID')`** has no `default=`, so it hard-crashes
   at import time if unset — acceptable, but make sure the **client secret** (if used server-side
   for token verification) is never logged or exposed in any API response/error message.
6. ~~**No rate limit on WebSocket connections** — `connectNotifSocket`/driver-location sockets can be
   opened repeatedly; consider a per-user connection cap to prevent resource exhaustion.~~
   **RESOLVED** in `45c4b23` + `4c1e1f4`. Root cause was broader than "no limit": DRF's throttles
   only run in the HTTP cycle, so WebSockets bypassed them entirely. `api_app/ws_limits.py` now adds
   three limits to all three consumers — a handshake rate limit per IP (30/60 s, code 4010, checked
   *before* auth), a per-user connection cap (5, code 4008) and a message rate limit (60 frames/10 s,
   code 4009). The handshake limit exists because a concurrency cap alone does nothing against a
   connect/disconnect loop (each disconnect frees the slot) and nothing at all against anonymous
   handshakes: measured 300/300 accepted on both paths before it was added.
   **Caveat:** counts are per-process, so N workers means N × cap — use nginx `limit_conn` for a
   hard global limit. Details in the module docstring.

## 🟠 High priority — Performance

1. **`torch` + `torchvision` in requirements.txt** for the ML waste classifier. These are large
   (~2GB+) and CPU-inference is slow per-request if the model runs synchronously inside the request/
   response cycle. Move classification to a background task (Celery/RQ) or an async queue so photo
   upload doesn't block on ML inference.
2. **No caching layer configured for production** — `CACHES` defaults to `LocMemCache`, and the
   Redis config is commented out as a manual step. LocMemCache doesn't share state across multiple
   worker processes (each Daphne/Gunicorn worker gets its own cache), which quietly breaks
   `cache_utils.py`'s effectiveness under any multi-worker deployment. Redis needs to be a mandatory
   prod setting, not optional.
3. **No image resizing/thumbnailing on upload.** Waste-report and license photos appear to be stored
   at original upload size and served as-is (e.g., 90px/48px thumbnails in the UI still load full-size
   files). Add server-side resizing (Pillow, already a dependency) to generate a thumbnail + a capped
   "full size" version — this alone can cut bandwidth/storage costs significantly.
4. **No CDN/S3 for media in production** — `MEDIA_ROOT` is local disk. Fine for single-server, but
   means no horizontal scaling (a second app server won't see the first server's uploaded photos) and
   no CDN edge caching. `boto3` is already a dependency (used for backups) — reuse it for
   `django-storages` + S3 for `MEDIA_URL`.
5. **No `LOGGING` config in `settings.py`.** Right now errors likely go to console/stdout only —
   fine for a container platform with log aggregation, but there's no structured logging, no
   Sentry/error-tracking integration, and no separation between INFO/WARNING/ERROR. Add a `LOGGING`
   dict plus `sentry-sdk` (or similar) so production errors are actually visible without SSH-ing in.

## 🟡 Medium priority — Admin Control

1. **Admin panel has no role granularity** — it's binary (`admin` role = full access to everything:
   backups, restore, user management, settings). Consider a `superadmin` vs. `operator` split so
   junior staff can manage requests/drivers without being able to restore the entire database or
   create other admins.
2. **Database restore is a single irreversible POST** (`/api/database-backups/restore/`) — it does
   take a safety backup first (good), but there's no confirmation step requiring re-entering a
   password, and no audit trail entry specifically for *who* triggered a restore and *when* beyond
   the generic toast. This is the single most destructive action in the whole admin panel and
   deserves extra friction.
3. **No bulk actions** in admin — requests, complaints, and schedules are all one-row-at-a-time.
   For a real municipality with hundreds of daily requests, bulk-assign / bulk-cancel / bulk-export
   (CSV) would save significant admin time.
4. **No CSV/Excel export anywhere** — admin logs, requests, and driver rosters are only viewable in
   the browser table. Municipalities often need this data in a spreadsheet for reporting to a council
   or ministry.

## 🟢 Medium priority — UX

1. **Guest requests (unauthenticated users) use `localStorage` tokens** (`guest_claim_tokens`) to
   later "claim" their request after registering — clever, but if the user clears browser data or
   switches devices before registering, those requests are permanently orphaned. Consider also
   sending a claim link to their phone/email at submission time as a backup.
2. **No offline/poor-connectivity handling** — Nepal has patchy mobile data in many areas; the app
   currently just shows "Connection lost" toasts. A service worker with basic offline queuing
   (submit request when back online) would meaningfully help field usage, especially for drivers.
3. **No skeleton loaders** — tables show "Loading..." as plain text rather than a skeleton/shimmer,
   which reads as slower than it is.
4. **Google Translate widget** is a heavyweight, sometimes-unreliable third-party dependency for a
   two-language (en/ne) app. A lightweight local i18n solution (Django's own `{% trans %}` +
   `django-modeltranslation` for DB content) would be faster, more reliable, and not depend on
   Google's translate endpoint staying available.

## New ideas / architectural upgrades worth considering

- **Background job queue (Celery + Redis, or RQ)** — this unlocks async ML inference, async email
  sending (currently synchronous in the request), scheduled backup pruning, and route generation
  for large batches without blocking a web worker.
- **Push notifications (Web Push / FCM)** instead of relying solely on the in-app WebSocket badge —
  drivers/admins get notified even when the tab isn't open.
- **Idempotency keys on request-creation** — a flaky mobile connection can cause the same waste
  request to be submitted twice; a client-generated idempotency key would dedupe safely server-side.
- **Structured driver ETA/tracking** — you already have live driver location; a "your collector is
  ~12 min away" estimate for the citizen (using the existing route/distance data) would be a strong
  differentiator with little new infrastructure.
- **Automated tests + CI** — `tests.py` exists in each app but scanning suggests light coverage;
  wiring GitHub Actions to run `manage.py test` on every push would catch regressions like the ones
  already fixed in your commit history (map crashes, double-submit bugs) before they reach prod.
- **Health-check endpoint** (`/healthz`) reporting DB/Redis/Channels connectivity — needed for any
  real load balancer or container orchestrator to know when to route traffic away from a bad instance.

---

### Suggested order of attack
1. Redis cache (mandatory, not optional) + `LOGGING`/error tracking — cheap, high leverage.
2. Move ML inference off the request path (background queue).
3. JWT → HttpOnly cookies + CSP header.
4. S3/CDN for media + image thumbnailing.
5. Admin role granularity + restore-action friction.
6. CSV export + bulk actions for admin.
