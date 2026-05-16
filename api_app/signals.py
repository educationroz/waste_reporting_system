"""
Django signals for cache invalidation and audit logging.
Invalidates dashboard cache when data changes.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .cache_utils import invalidate_dashboard_cache
from .models import WasteRequest, Driver, Vehicle, Route


@receiver(post_save, sender=WasteRequest)
def invalidate_cache_on_request_save(sender, instance, created, **kwargs):
    """Invalidate dashboard cache when a waste request is created/updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=WasteRequest)
def invalidate_cache_on_request_delete(sender, instance, **kwargs):
    """Invalidate dashboard cache when a waste request is deleted."""
    invalidate_dashboard_cache()


@receiver(post_save, sender=Driver)
def invalidate_cache_on_driver_save(sender, instance, created, **kwargs):
    """Invalidate dashboard cache when a driver is created/updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=Driver)
def invalidate_cache_on_driver_delete(sender, instance, **kwargs):
    """Invalidate dashboard cache when a driver is deleted."""
    invalidate_dashboard_cache()


@receiver(post_save, sender=Vehicle)
def invalidate_cache_on_vehicle_save(sender, instance, created, **kwargs):
    """Invalidate dashboard cache when a vehicle is created/updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=Vehicle)
def invalidate_cache_on_vehicle_delete(sender, instance, **kwargs):
    """Invalidate dashboard cache when a vehicle is deleted."""
    invalidate_dashboard_cache()


@receiver(post_save, sender=Route)
def invalidate_cache_on_route_save(sender, instance, created, **kwargs):
    """Invalidate dashboard cache when a route is created/updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=Route)
def invalidate_cache_on_route_delete(sender, instance, **kwargs):
    """Invalidate dashboard cache when a route is deleted."""
    invalidate_dashboard_cache()
