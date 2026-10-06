# web_app/context_processors.py
#
# Exposes GOOGLE_CLIENT_ID and system branding (site name, logo, tagline) to all templates.

import logging

from django.conf import settings
from django.core.cache import cache
from django.db.utils import DatabaseError

logger = logging.getLogger(__name__)


def google_client_id(request):
    raw_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '') or ''
    return {
        'GOOGLE_CLIENT_ID': str(raw_id).strip().strip('"\''),
    }


def system_branding(request):
    # A context processor runs on EVERY template render, so it must never raise:
    # an unreachable cache backend would otherwise turn a Redis blip into a
    # site-wide 500.
    #
    # PERF: single cache round-trip per page (was 3x cache.get + 3x cache.set).
    # On remote Redis (e.g. Redis Cloud) each round-trip costs ~400-500ms from
    # local dev, so 3 keys alone added ~1.4s to EVERY page load.
    defaults = {
        'site_branding_name': 'SafhaSahar',
        'site_branding_logo': '',
        'site_branding_tagline': 'Live Waste Reporting System',
    }
    try:
        branding = cache.get('site_branding')
    except Exception:  # noqa: BLE001 - cache backend unreachable
        logger.warning('system_branding: cache unavailable; using defaults.')
        branding = None

    if isinstance(branding, dict) and branding:
        site_name = branding.get('site_branding_name', 'SafhaSahar')
        site_logo = branding.get('site_branding_logo', '')
        site_tagline = branding.get('site_branding_tagline', 'Live Waste Reporting System')
    else:
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
        except DatabaseError:
            logger.warning('system_branding: database unavailable; using defaults.')
            site_name = 'SafhaSahar'
            site_logo = ''
            site_tagline = 'Live Waste Reporting System'

        try:
            cache.set('site_branding', {
                'site_branding_name': site_name,
                'site_branding_logo': site_logo,
                'site_branding_tagline': site_tagline,
            }, 3600)
        except Exception:  # noqa: BLE001 - cache backend unreachable
            logger.warning('system_branding: could not write branding to cache.')

    return {
        'SITE_NAME': site_name or 'SafhaSahar',
        'SITE_TAGLINE': site_tagline or 'Live Waste Reporting System',
        'SITE_LOGO_URL': site_logo or '',
    }