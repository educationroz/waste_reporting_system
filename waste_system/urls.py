"""
URL configuration for waste_system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.decorators.cache import cache_page
from django.views.i18n import JavaScriptCatalog

from waste_system.health import healthz, healthz_live

urlpatterns = [
    # ── Health checks ────────────────────────────────────────────────────────
    # Registered first so they can never be shadowed by the catch-all
    # web_app include at the bottom of this list, and so a probe costs the
    # shortest possible URL resolution.
    #
    #   /healthz/live  liveness  — no dependencies, 200 while the worker runs
    #   /healthz       readiness — DB + cache + Channels (+ Redis), 503 on fail
    #
    # /healthz/live is declared BEFORE /healthz even though they cannot
    # collide, purely to keep the more specific route adjacent to its parent.
    # Both are in SECURE_REDIRECT_EXEMPT (settings.py) so SECURE_SSL_REDIRECT
    # does not answer a plain-HTTP probe with a 301 that reads as "unhealthy".
    path('healthz/live', healthz_live, name='healthz-live'),
    path('healthz', healthz, name='healthz'),

    path('admin/', admin.site.urls),

    # auth_app REST API
    path('auth/', include('auth_app.urls')),

    # api_app REST API
    path('api/', include('api_app.urls')),

    # Django's built-in set_language view — POST {'language': 'ne'} here to
    # switch languages. It writes the choice into the session (and a
    # django_language cookie for anonymous visitors) and LocaleMiddleware
    # picks it up on the very next request. Powers the language switcher
    # in base.html; replaces the old googtrans localStorage/cookie hack.
    path('i18n/', include('django.conf.urls.i18n')),

    # JavaScript translation catalog. A lot of user-facing text on the
    # dashboards is produced by inline JS (showToast(...), status badges
    # rebuilt after an AJAX update, confirm() prompts), which {% trans %}
    # cannot reach because it only runs at template-render time. This view
    # ships the same locale/<lang>/LC_MESSAGES catalog to the browser and
    # defines a global gettext() there, so those strings translate too.
    # Cached per-language because the catalog is static between deploys.
    path(
        'jsi18n/',
        # No `packages` argument on purpose: this project's catalog lives in
        # LOCALE_PATHS (locale/<lang>/LC_MESSAGES/django.po), not inside an
        # installed app's own locale dir. Passing packages= would restrict the
        # view to those apps' catalogs and drop every string we translated.
        # domain='django' (not the 'djangojs' default): this project keeps a
        # SINGLE catalog, locale/<lang>/LC_MESSAGES/django.po, shared by the
        # templates and the inline scripts. Labels like "Completed" or
        # "Available" appear in both, so one domain means one msgid and one
        # translation instead of two copies that can drift apart.
        cache_page(86400, key_prefix='jsi18n')(
            JavaScriptCatalog.as_view(domain='django')
        ),
        name='javascript-catalog',
    ),

    # web_app HTML pages (catch-all last)
    path('', include('web_app.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)