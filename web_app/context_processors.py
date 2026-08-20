# web_app/context_processors.py
#
# Exposes GOOGLE_CLIENT_ID from settings.py (configured via .env) to all templates.

from django.conf import settings


def google_client_id(request):
    raw_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '') or ''
    return {
        'GOOGLE_CLIENT_ID': str(raw_id).strip().strip('"\''),
    }