# web_app/context_processors.py
#
# Exposes GOOGLE_CLIENT_ID and system branding (site name, logo, tagline) to all templates.

from django.conf import settings
from django.core.cache import cache


def google_client_id(request):
    raw_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '') or ''
    return {
        'GOOGLE_CLIENT_ID': str(raw_id).strip().strip('"\''),
    }


def system_branding(request):
    site_name = cache.get('site_branding_name')
    site_logo = cache.get('site_branding_logo')
    site_tagline = cache.get('site_branding_tagline')

    if site_name is None:
        try:
            from api_app.models import SystemSettings
            branding_setting = SystemSettings.objects.filter(key='site_branding').first()
            if branding_setting and isinstance(branding_setting.value, dict):
                site_name = branding_setting.value.get('site_name', 'SafhaSahar')
                site_logo = branding_setting.value.get('site_logo', '')
                site_tagline = branding_setting.value.get('site_tagline', 'Live Waste Reporting System')
            else:
                site_name = 'SafhaSahar'
                site_logo = ''
                site_tagline = 'Live Waste Reporting System'
        except Exception:
            site_name = 'SafhaSahar'
            site_logo = ''
            site_tagline = 'Live Waste Reporting System'

        cache.set('site_branding_name', site_name, 3600)
        cache.set('site_branding_logo', site_logo, 3600)
        cache.set('site_branding_tagline', site_tagline, 3600)

    return {
        'SITE_NAME': site_name or 'SafhaSahar',
        'SITE_TAGLINE': site_tagline or 'Live Waste Reporting System',
        'SITE_LOGO_URL': site_logo or '',
    }