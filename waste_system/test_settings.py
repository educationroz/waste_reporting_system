"""Settings used by the test suite and CI.

Import the real settings, then override only what makes tests fast and their
output readable. Run with::

    python manage.py test --settings=waste_system.test_settings
"""

import os

# The shipping settings intentionally fail closed with DEBUG=False. Tests use
# their isolated configuration and do not exercise HTTPS redirects, so opt in
# before importing the base settings rather than weakening the production
# default.
os.environ['DEBUG'] = 'True'

from .settings import *  # noqa: F401,F403

# Application loggers stay silent so a failure trace isn't buried in INFO
# chatter. api_app/views.py emits a notification line per push, which is
# dozens of lines in a full run.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'null': {'class': 'logging.NullHandler'}},
    'root': {'handlers': ['null'], 'level': 'CRITICAL'},
    'loggers': {
        'notif_debug': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
        'backup': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
        'django.request': {'handlers': ['null'], 'level': 'CRITICAL', 'propagate': False},
    },
}

# Hashing dominates runtime when tests create users; MD5 is fine for throwaway
# fixtures and measurably faster than the default PBKDF2.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# In-memory channel layer: no Redis dependency in CI.
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# Throttling would make repeated requests in a test 429 unpredictably. The
# rates cannot simply be emptied: DRF raises ImproperlyConfigured for any scope
# a view references, so every existing key is kept and set very high instead.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_RATES': {
        scope: '100000/day'
        for scope in REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})  # noqa: F405
    },
}

# Keep the CSP in its default mode so header tests assert the shipping default
# rather than whatever an environment variable happens to be set to.
CSP_MODE = 'compat'
CSP_REPORT_URI = ''

# Local-memory cache: avoids cross-test bleed through a shared backend.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}
