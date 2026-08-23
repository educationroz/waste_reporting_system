"""
waste_system/settings.py
Full project settings. Uses python-decouple for .env management.
pip install python-decouple
"""

from pathlib import Path
from datetime import timedelta
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='change-me-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Whether registration should do a live DNS/MX lookup on the email domain.
# Defaults to "on in production, off in development". It is exposed as its own
# setting (rather than being derived from DEBUG inline) because Django's test
# runner forces DEBUG=False, which previously turned the network lookup on
# during tests and made any test using an example.com address fail.
EMAIL_CHECK_DELIVERABILITY = config(
    'EMAIL_CHECK_DELIVERABILITY', default=not DEBUG, cast=bool
)

# ─── Apps ─────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'jazzmin',  # Admin theme
    'daphne',  # must be FIRST for ASGI
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'channels',
    'corsheaders',

    # Project apps
    'auth_app',
    'api_app',
    'web_app',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # must be first
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Must come after SessionMiddleware (reads the user's saved language from
    # the session) and before CommonMiddleware (which needs the active
    # language already resolved to redirect correctly). This is what makes
    # {% trans %}/{% blocktrans %} and get_FOO_display() render in the
    # visitor's chosen language on every request — replaces the old
    # Google Translate widget, which translated the DOM client-side after
    # the fact and depended on a third-party endpoint staying reachable.
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # CSP + hardening headers. Last so it sees the final response.
    'waste_system.security.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'waste_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Exposes LANGUAGE_CODE / LANGUAGES / get_current_language in
                # every template — powers the <html lang="{{ LANGUAGE_CODE }}">
                # attribute and the language switcher in base.html.
                'django.template.context_processors.i18n',
                'web_app.context_processors.google_client_id',
                # Exposes {{ csp_nonce }} so inline <script> tags can carry a
                # per-request nonce and survive the strict CSP.
                'waste_system.security.csp_nonce',
            ],
        },
    },
]

WSGI_APPLICATION = 'waste_system.wsgi.application'
ASGI_APPLICATION = 'waste_system.asgi.application'

# Deliberately SAMEORIGIN, not DENY (Django's check --deploy suggests DENY as
# security.W019). This app previews driver-licence PDFs with same-origin
# <embed src="...">, which Chrome/Safari treat as framing — DENY would blank
# those previews. CSP `frame-ancestors 'self'` (see waste_system/security.py)
# is the modern equivalent and is set consistently with this value.
X_FRAME_OPTIONS = 'SAMEORIGIN'
SECURE_CONTENT_TYPE_NOSNIFF = True

# ─── Session cookie hardening ─────────────────────────────────────────────────
# The browser UI authenticates with this session cookie instead of a JWT held
# in localStorage. HttpOnly is the entire point: it makes the credential
# unreadable to JavaScript, so an XSS bug can no longer exfiltrate a token that
# stays valid for days. (It does NOT stop an attacker acting as the user inside
# the page — for that, see the CSP below and keep escaping output.)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'   # blocks cross-site sends on top-level POSTs
# CSRF cookie must stay readable by JS: fetch() copies it into X-CSRFToken.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
# Rolling expiry so an idle session eventually dies.
SESSION_COOKIE_AGE = 60 * 60 * 12          # 12 hours
SESSION_SAVE_EVERY_REQUEST = True          # refresh the window on activity

# ─── Content-Security-Policy ──────────────────────────────────────────────────
# 'compat' → old permissive behaviour ('unsafe-inline' script-src).
# 'report' → enforce permissive, but ALSO send the strict nonce policy as
#            Report-Only so violations show up without breaking anything.
# 'strict' → enforce the nonce + 'strict-dynamic' policy. Inline on* handlers
#            stop running, so only flip this after 'report' mode is quiet.
# Roll out as: compat → report (read the reports) → strict.
CSP_MODE = config('CSP_MODE', default='compat')

# Optional endpoint that receives JSON violation reports (e.g. a Sentry CSP
# ingest URL). Empty string disables report-uri/report-to entirely.
CSP_REPORT_URI = config('CSP_REPORT_URI', default='')

if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000  # 1 year, per HSTS preload requirements
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
# ─── Database ─────────────────────────────────────────────────────────────────
# Use SQLite for development, PostgreSQL for production
DB_ENGINE = config('DB_ENGINE', default='sqlite3')  # 'postgresql' or 'sqlite3'

if DB_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='waste_db'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
            # Reuse TCP connections across requests instead of opening a new
            # one every request — a real cost once you're on Postgres over a
            # network connection rather than local SQLite. 600s (10 min) is
            # a safe default; if this ever sits behind pgbouncer in
            # transaction-pooling mode, set this to 0 instead (pgbouncer
            # manages pooling itself at that point).
            'CONN_MAX_AGE': config('CONN_MAX_AGE', default=600, cast=int),
            'CONN_HEALTH_CHECKS': True,  # validate a pooled connection before reuse
        }
    }
else:  # SQLite (default for development)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

GOOGLE_OAUTH_CLIENT_ID = config('GOOGLE_OAUTH_CLIENT_ID', default='')
# ─── Caching ───────────────────────────────────────────────────────────────────
# Default: In-memory cache for development. Switch to Redis for production.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'waste-management-cache',
        'OPTIONS': {
            'MAX_ENTRIES': 10000
        },
        'KEY_PREFIX': 'waste_',
        'TIMEOUT': 300,  # 5 minutes default
    }
}

# For production, replace above with Redis:
# CACHES = {
#     'default': {
#         'BACKEND': 'django_redis.cache.RedisCache',
#         'LOCATION': 'redis://127.0.0.1:6379/1',
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#             'CONNECTION_POOL_KWARGS': {'max_connections': 50}
#         }
#     }
# }

# ─── Custom User Model ────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'auth_app.User'

<<<<<<< HEAD
=======
# NOTE: GOOGLE_OAUTH_CLIENT_ID is defined once, above, with default=''. A second
# assignment used to sit here without a default, silently overriding it and
# hard-crashing at import time whenever the variable was unset — which is why a
# fresh checkout could not even run `manage.py check`. GoogleLoginView already
# handles the empty case by returning 503 "not configured", which is the right
# behaviour: an unconfigured optional integration should disable itself, not
# take down the whole site.
>>>>>>> b89a62fbbe93201c3b4ab2be297aacb3c0f1ba4d

# ─── Password Validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── DRF ─────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # ← add this FIRST
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # ─── Rate limiting (throttling) ────────────────────────────────────────
    # AnonRateThrottle keys off the client IP (no login needed).
    # UserRateThrottle keys off the authenticated user PK.
    # ScopedRateThrottle is opt-in per-view: set throttle_scope on a view.
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Generic global caps — apply to *every* DRF view by default unless
        # the view overrides throttle_classes or throttle_scope.
        'anon': '20/min',
        'user': '200/min',
        # Heavier per-endpoint scopes. Apply these to sensitive endpoints by
        # setting `throttle_scope = '<name>'` on the view class.
        # ─ Authentication / brute‑force targets ─────────────────────
        'login':                    '5/min',      # 5 wrong passwords/min → locked out temporarily (per IP)
        'session_login':            '5/min',      # Django session-login form
        'register':                 '6/hour',     # 6 new accounts/hr/IP — spam mitigation
        # ─ Email‑sending endpoints (avoid bombing users' inboxes) ───
        'resend_verification':      '3/hour',     # 3 re-verify email attempts/hr
        'password_reset_request':   '3/hour',     # 3 forgot-password emails/hr/IP
        'password_reset_confirm':   '10/min',     # Reset-password form submit (cheap but don't spam)
        # ─ Other auth endpoints ─────────────────────────────────────
        'logout':                   '20/min',
        'token_refresh':            '30/min',
        'change_password':          '10/min',
        'verify_email':             '30/min',     # Clicking the email verify link (GET)
    },
}
# ─── JWT ─────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS':  True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ─── Channels Layer ────────────────────────────────────────────────────────────
# Redis backend requires Redis 5.0+ (BZPOPMIN support).
# For local development, the project now safely falls back to the in-memory backend
# when Redis support is unavailable or when USE_REDIS is not enabled.
USE_REDIS = config('USE_REDIS', default=False, cast=bool)
REDIS_HOST = config('REDIS_HOST', default='127.0.0.1')
REDIS_PORT = config('REDIS_PORT', default=6379, cast=int)
REDIS_PASSWORD = config('REDIS_PASSWORD', default='')

if USE_REDIS:
    try:
        import channels_redis  # noqa: F401
    except ImportError:
        USE_REDIS = False

if USE_REDIS:
    redis_host_config = (REDIS_HOST, REDIS_PORT)
    if REDIS_PASSWORD:
        redis_host_config = (REDIS_HOST, REDIS_PORT, {'password': REDIS_PASSWORD})

    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [redis_host_config],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# ─── WebSocket limits ─────────────────────────────────────────────────────────
# DRF's throttles only run in the HTTP cycle, so WebSockets bypass them
# entirely. Without these, one authenticated account (or one stolen session
# cookie) could open unbounded sockets — each costing a channel-layer group
# membership, an event-loop task, and a Redis subscription in production.
#
# Counts are per-process: with N workers the effective ceiling is
# N × WS_MAX_CONNECTIONS_PER_USER. For a hard global cap, use nginx's
# `limit_conn` on the WebSocket location. See api_app/ws_limits.py.
WS_MAX_CONNECTIONS_PER_USER = config('WS_MAX_CONNECTIONS_PER_USER', default=5, cast=int)
WS_MAX_MESSAGES_PER_WINDOW = config('WS_MAX_MESSAGES_PER_WINDOW', default=60, cast=int)
WS_MESSAGE_WINDOW_SECONDS = config('WS_MESSAGE_WINDOW_SECONDS', default=10, cast=int)
# Handshake churn, keyed by client IP and checked BEFORE auth. The connection
# cap only limits concurrent sockets, so it does nothing against a
# connect/disconnect loop (each disconnect frees the slot) and nothing at all
# against anonymous handshakes. Keyed by IP, so shared-NAT clients share the
# budget — keep it generous. Set to 0 to disable.
WS_MAX_HANDSHAKES_PER_WINDOW = config('WS_MAX_HANDSHAKES_PER_WINDOW', default=30, cast=int)
WS_HANDSHAKE_WINDOW_SECONDS = config('WS_HANDSHAKE_WINDOW_SECONDS', default=60, cast=int)
# Staff are capped too by default: an admin session is the most valuable one to
# steal. Set True only if an ops dashboard legitimately needs many sockets.
WS_EXEMPT_STAFF = config('WS_EXEMPT_STAFF', default=False, cast=bool)

# ─── Logging ──────────────────────────────────────────────────────────────────
# Replaces a stray logging.basicConfig(level=INFO) that used to run at import
# time in api_app/views.py. That call reconfigured the ROOT logger for the whole
# process, so every management command and test run was flooded with INFO lines.
#
# LOG_LEVEL controls the app's own loggers. Tests set it to CRITICAL so failure
# output stays readable.
LOG_LEVEL = config('LOG_LEVEL', default='INFO' if DEBUG else 'WARNING')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
        # Application loggers.
        'notif_debug': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'backup': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        # django.request logs a WARNING for every 4xx. Those are normal here —
        # the test suite deliberately asserts 401/403/404 responses — so keep
        # them at ERROR to avoid drowning real problems.
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
    },
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
CORS_ALLOW_CREDENTIALS = True

# ─── Localisation ─────────────────────────────────────────────────────────────
# Local Django i18n replaces the old Google Translate widget: instead of a
# third-party script rewriting the rendered DOM client-side (slow, an extra
# network dependency, and prone to silently failing — see base.html's old
# __ssTranslateLoadFailed handling), every {% trans %}/{% blocktrans %} tag
# and every get_FOO_display() call now renders server-side in whichever
# language LocaleMiddleware resolves for the request (URL prefix → saved
# session language → browser Accept-Language header → LANGUAGE_CODE).
LANGUAGE_CODE = 'en-us'
LANGUAGES = [
    ('en', 'English'),
    ('ne', 'नेपाली'),  # Nepali
]
# django-admin makemessages / compilemessages read and write .po/.mo files here.
LOCALE_PATHS = [BASE_DIR / 'locale']
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ─── Static / Media ───────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── File Upload Security ─────────────────────────────────────────────────────
# Per-photo cap — validators.py's MAX_IMAGE_SIZE reads this value directly
# (with a 3MB fallback if this setting is ever missing), so there is exactly
# ONE number controlling "how big can one photo be", not two that can drift
# out of sync.
MAX_PHOTO_SIZE = 3 * 1024 * 1024          # 3MB per individual photo

# Hard server-side cap on how many 'extra_photos' a single WasteRequest can
# attach — views.py's WasteRequestViewSet.create() rejects anything over
# this BEFORE the request is processed or any ML inference runs.
MAX_EXTRA_PHOTOS = 5

# Reconciled against MAX_PHOTO_SIZE above: previously this was 5MB total
# while each photo was independently allowed up to 5MB, so 2+ photos in one
# request were always rejected by Django before any validator ever ran.
# 20MB gives headroom for 1 primary + MAX_EXTRA_PHOTOS additional photos at
# MAX_PHOTO_SIZE each, plus the rest of the multipart form fields.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024   # 20MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Login Redirect ───────────────────────────────────────────────────────────
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'

# ─── Email (used for account verification links) ──────────────────────────────
# Dev default: prints emails to the runserver console instead of sending them.
# In production, set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# and the EMAIL_HOST_* / EMAIL_PORT / EMAIL_USE_TLS vars in your .env.
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@wastesystem.local')


# Backup/restore configuration
BACKUP_RETENTION_DAYS = 30          # local backups older than this get pruned by the scheduled command
BACKUP_OFFSITE_ENABLED = False      # set True once S3 credentials below are configured
BACKUP_S3_BUCKET = None             # e.g. 'my-app-db-backups'
BACKUP_S3_ENDPOINT_URL = None       # only needed for non-AWS S3-compatible storage (Backblaze, MinIO, etc.)