from django.apps import AppConfig


class ApiAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_app'
    verbose_name = 'API & WebSocket'

    def ready(self):
        """Register signals when app is ready."""
        import api_app.signals  # noqa