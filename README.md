# Smart Waste Collection — Waste Reporting System

A full-stack waste management platform for Nepalese municipalities. Citizens report
waste issues with photo evidence (optionally guest-claimed), ML classifies the
waste type and flags suspicious submissions, and admins manage drivers, vehicles,
routes, schedules, complaints and backups in real time over WebSockets.

Built with **Django 5.2**, **Django REST Framework**, **Channels (WebSocket)**,
**PyTorch** for photo analysis, and a responsive multilingual UI (i18n, timezone
`Asia/Kathmandu`).

---

## Features

- **Citizen reporting** — submit waste reports with geo-location + photos
- **Guest submissions with auto-link** — report without an account, then log in
  later and the report is automatically linked to your profile
- **ML photo validation** — photos are classified and flagged for manual review
  when they look suspicious, anonymized/unsafe, or don't match the claimed type
- **3-role dashboard system**
  - **Citizen** — report, track own requests + complaints, claim guest requests
  - **Driver** — assigned pickups, live status updates (WebSocket), location share
  - **Admin** — everything: requests, complaints, bulk actions, drivers, vehicles,
    routes, schedules, settings, activity (audit) log, database backups
- **Real-time WebSockets** — live notifications and live driver-location map
- **Secure auth** — JWT + session login, Google Sign-In (optional), email
  verification, password reset, biometric device tokens, per-endpoint rate limits
- **Audit trail** — every admin action is logged (append-only, no fabrication)
- **Backup / restore** — encrypted database + media backups from the admin UI
- **Hardened** — strict upload validation, role-based API lockdown, CSP headers,
  CSRF-protected web logout, throttled brute-force surface

---

## Tech Stack

| Layer        | Technology |
|--------------|-------------|
| Backend      | Django 5.2, Django REST Framework, Channels, daphne (ASGI) |
| Auth         | DRF SimpleJWT, Google OAuth, session auth for web |
| ML           | PyTorch + TorchVision (photo classification / review flags) |
| Database     | SQLite (dev) / PostgreSQL (prod) |
| Cache/WS     | Optional Redis (`USE_REDIS=false` by default → in-memory + InMemory channel layer) |
| Static       | WhiteNoise (`CompressedStaticFilesStorage`) |
| Admin        | django-jazzmin |
| Frontend     | Server-rendered templates (Django i18n) + Bootstrap + vanilla JS, Leaflet map |

---

## Project Structure

```
waste_reporting_system/
├── waste_system/      # project settings, URLs, CSP/security, ASGI/WSGI
├── core/              # shared helpers / model mixins
├── auth_app/          # users, JWT/session/login/register, Google login, email flows
├── api_app/           # the REST API: requests, drivers, vehicles, routes, schedules,
│                      # checkpoints, complaints, notifications, logs, backups, ML, WS consumers
├── web_app/           # server-rendered pages (home, dashboards, management, settings)
├── templates/         # all HTML templates (web_app/, auth pages)
├── static/            # CSS/JS/images (collected into staticfiles/)
├── media/             # uploaded photos / PDFs (gitignored)
├── ml_models/         # ML model artifacts
├── backups/           # DB + media backups (gitignored)
└── locale/            # translation catalogs
```

---

## Quick Start (Windows / Linux)

> Requires **Python 3.11+** (project runs on 3.14).

```bash
# 1. Clone & enter
git clone https://github.com/educationroz/waste_reporting_system.git
cd waste_reporting_system

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Linux/macOS

# 3. Environment config — copy example and fill it in
cp .env.example .env
#   (on Windows:  copy .env.example .env)

# 4. Install dependencies
pip install -r requirements.txt
#   Linux note: python-magic needs the system library:
#     sudo apt-get install -y libmagic1

# 5. Migrate, collect static, create a superuser, run
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py runserver
```

Or use the provided launcher: `bash run.sh` (dev) / `bash run.sh production` (ASGI via daphne).

---

## Environment Variables (`.env`)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SECRET_KEY` | ✅ | — | Django secret — generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | — | `True` | Dev mode serves static/media; `False` enables HSTS, HTTPS redirect, secure cookies |
| `ALLOWED_HOSTS` | — | `localhost,127.0.0.1,0.0.0.0` | Comma-separated hosts |
| `DB_ENGINE` | ✅ in prod | `sqlite3` | `sqlite3` or `postgresql` (prod refuses to start without it) |
| `DB_NAME/USER/PASSWORD/HOST/PORT` | prod | — | Postgres connection |
| `CONN_MAX_AGE` | — | `600` | DB connection persistence (seconds) |
| `USE_REDIS` | — | `false` | Redis for caching + WebSocket channel layer (needed for multi-worker) |
| `REDIS_HOST/PORT/PASSWORD` | if Redis | — | Redis connection |
| `GOOGLE_OAUTH_CLIENT_ID` | — | empty | Enables the Google Sign-In button when set |
| `CSP_MODE` | — | `compat` | CSP rollout: `compat` → `report` → `strict` |
| `CSP_REPORT_URI` | — | — | CSP violation report endpoint |
| `EMAIL_BACKEND` | — | console | `console` in dev; SMTP in prod |
| `EMAIL_HOST/PORT/USE_TLS/USER/PASSWORD` | prod | — | SMTP settings |
| `DEFAULT_FROM_EMAIL` | — | `noreply@example.com` | Sender address |
| `EMAIL_CHECK_DELIVERABILITY` | — | `False` | DNS/MX check on registration (defaults on in prod) |

`.env` is gitignored — never commit real secrets.

---

## Running Tests

```bash
python manage.py test            # full suite — 83 tests
python manage.py check           # system checks
python manage.py makemigrations --check --dry-run   # verify no pending migrations
```

Health endpoint: `GET /healthz` (liveness + readiness: DB, cache, channel layer).

---

## API Overview (main endpoints)

All under `/api/`. Auth via `Authorization: Bearer <access>` (JWT) or session.

| Area | Endpoints |
|------|-----------|
| Auth (`/api/auth/`) | `login/`, `register/`, `google-login/`, `token/refresh/`, `logout/`, `profile/`, `change-password/`, `session-login/`, `verify-email/`, `resend-verification/`, `password-reset/`, `password-reset-confirm/` |
| Waste requests | `GET/POST /api/waste-requests/`, `update_status/`, `assign_driver/`, `claim_guest_requests/`, `bulk_assign_driver/`, `bulk_cancel/`, `export/` |
| Notifications | `GET /api/notifications/`, `unread/`, `mark_all_read/`, `clear_all/` |
| Complaints | `GET/POST /api/complaints/`, `update_status/`, `bulk_update_status/` |
| Drivers | `/api/drivers/`, `public-locations/`, `create-account/` |
| Others | `/api/vehicles/`, `/api/routes/` (`generate/`, `optimize/`), `/api/schedules/` (`bulk_export/`), `/api/checkpoints/` (`bulk_delete/`), `/api/bins/`, `/api/admin-logs/`, `/api/system-settings/`, `/api/database-backups/` |

**WebSockets:** `/ws/notifications/` (live toasts), `/ws/driver-locations/` (live map).

### Guest-report auto-link flow

1. Anonymous visitor submits a report → the browser generates a `guest_token`
   (stored in localStorage) and sends it with the request.
2. On login, the pending tokens are sent to
   `POST /api/waste-requests/claim_guest_requests/` with `{ "guest_tokens": [...] }`.
3. Unclaimed reports (`user__isnull=True`) get linked to the account and the user
   receives a *"Request Linked to Your Account"* notification.

> The token is never exposed in notification payloads, so guests can only claim
> their own submissions.

---

## Important Security Notes

- Uploads (photos, logos, PDFs) are validated, sanitized, compressed and
  whitelisted by extension — never written raw to `MEDIA`.
- Admin audit logs are append-only: no client can create or edit entries.
- Auth endpoints are rate-limited; logout is POST-only (CSRF protected).
- `role` / `email` / request `status` / complaint verdicts are server-side only.
- In production, run behind **daphne** (`waste_system.asgi`), serve `/media/` via
  nginx/cloud storage, and set `DEBUG=False` + `USE_REDIS=true`.

---

## Documentation

- `HEALTHCHECK.md` — health/readiness endpoint & deployment notes
- `TESTING.md` — test suite guide
- `SECURITY-auth-hardening.md` / `SECURITY-csp.md` — security hardening details
- `QUICK_REFERENCE_GUIDE.md` — endpoint & workflow reference
- `ADMIN_DASHBOARD.md` / `ADMIN_IMPLEMENTATION_SUMMARY.md` — admin panel docs
- `ROUTE_OPTIMIZATION_GUIDE.md` — route planning engine

---

## Created by

- [Aayush KC](https://github.com/Aayushkassey) — Full Stack Django & ML
- [Roz Thapa Mage](https://github.com/educationroz) — Full Stack Django

---

## License

Private / in-house — ask the project owner before redistributing.