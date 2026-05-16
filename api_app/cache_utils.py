"""
Cache utility functions for dashboard and API performance.
Handles cache invalidation when data changes.
"""

from django.core.cache import cache


def invalidate_dashboard_cache():
    """Invalidate admin dashboard statistics cache."""
    cache.delete('admin_dashboard_stats')


def invalidate_all_caches():
    """Clear all application caches."""
    cache.clear()
