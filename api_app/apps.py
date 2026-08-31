from django.apps import AppConfig


class ApiAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_app'
    verbose_name = 'API & WebSocket'

    def ready(self):
        """Register signals when app is ready."""
        import atexit

        import api_app.signals  # noqa

        # Gracefully drain the background ML thread pool so in-flight
        # inference finishes before the process exits (avoids a torn write).
        from api_app.tasks import shutdown_executor
        atexit.register(shutdown_executor)