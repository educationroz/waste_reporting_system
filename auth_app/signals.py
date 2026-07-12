from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from api_app.models import Driver

User = get_user_model()


@receiver(post_save, sender=User)
def sync_driver_profile(sender, instance, created, **kwargs):
    """Ensure every driver user has a corresponding Driver profile row."""
    if instance.role != 'driver':
        return

    Driver.objects.get_or_create(
        user=instance,
        defaults={
            'license_number': f'DRIVER-{instance.id}',
            'is_available': True,
        },
    )
