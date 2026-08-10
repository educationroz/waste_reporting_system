# web_app/context_processors.py
#
# Yo file NAYA banauNuhos (web_app app bhitra, models.py/views.py sanga
# ekai thau ma). Yesle GOOGLE_OAUTH_CLIENT_ID lai settings.py (jun .env
# bata aaucha) bata lera, HAREK template ma automatically available
# garaidincha — matlab kunai pani view function ma manually pass garnu
# pardaina.

from django.conf import settings


def google_client_id(request):
    return {
        'GOOGLE_CLIENT_ID': settings.GOOGLE_OAUTH_CLIENT_ID,
    }