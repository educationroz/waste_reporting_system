"""
Admin utilities for logging actions and managing audit trails.
"""
from api_app.models import AdminLog
from django.conf import settings
import json


def get_client_ip(request):
    """
    Extract client IP from request.
    Handles X-Forwarded-For header for proxied requests.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_admin_action(admin_user, action, content_type, object_id=None,
                     object_description='', changes=None, request=None):
    """
    Log an admin action to the audit trail.
    
    Args:
        admin_user: User object (admin who performed action)
        action: String - 'create', 'update', 'delete', 'assign', 'status_change', 'login', etc.
        content_type: String - model name (e.g., 'Driver', 'Vehicle', 'WasteRequest')
        object_id: Integer - ID of affected object (optional)
        object_description: String - human-readable description
        changes: Dict - before/after values for update actions
        request: HttpRequest object (for IP and user agent)
    
    Returns:
        AdminLog instance
    """
    if changes is None:
        changes = {}
    
    ip_address = None
    user_agent = ''
    
    if request:
        ip_address = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    log_entry = AdminLog.objects.create(
        admin_user=admin_user,
        action=action,
        content_type=content_type,
        object_id=object_id,
        object_description=object_description,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    
    return log_entry


def log_model_change(admin_user, instance, action, request=None, old_values=None):
    """
    Log a model instance change.
    
    Args:
        admin_user: User object (admin who performed action)
        instance: Model instance that was changed
        action: String - 'create', 'update', or 'delete'
        request: HttpRequest object (optional)
        old_values: Dict of old values (for update actions)
    """
    changes = {}
    if old_values:
        # Create diff of changes
        for field, old_value in old_values.items():
            new_value = getattr(instance, field, None)
            if old_value != new_value:
                changes[field] = {
                    'old': str(old_value),
                    'new': str(new_value),
                }
    
    return log_admin_action(
        admin_user=admin_user,
        action=action,
        content_type=instance.__class__.__name__,
        object_id=instance.id,
        object_description=str(instance),
        changes=changes,
        request=request,
    )


def get_admin_activity_summary(days=7):
    """
    Get a summary of admin activities over the last N days.
    
    Args:
        days: Number of days to look back
    
    Returns:
        Dict with activity summary
    """
    from django.utils import timezone
    from datetime import timedelta
    
    since = timezone.now() - timedelta(days=days)
    logs = AdminLog.objects.filter(created_at__gte=since)
    
    summary = {
        'total_actions': logs.count(),
        'by_action': {},
        'by_admin': {},
        'by_content_type': {},
    }
    
    for log in logs:
        # Count by action
        action = log.get_action_display()
        summary['by_action'][action] = summary['by_action'].get(action, 0) + 1
        
        # Count by admin
        admin_name = log.admin_user.username if log.admin_user else 'System'
        summary['by_admin'][admin_name] = summary['by_admin'].get(admin_name, 0) + 1
        
        # Count by content type
        summary['by_content_type'][log.content_type] = \
            summary['by_content_type'].get(log.content_type, 0) + 1
    
    return summary


def cleanup_old_logs(days=90):
    """
    Delete admin logs older than N days.
    Useful for keeping database size manageable.
    
    Args:
        days: Number of days to keep
    
    Returns:
        Tuple of (deleted_count, deleted_bytes_estimate)
    """
    from django.utils import timezone
    from datetime import timedelta
    
    cutoff = timezone.now() - timedelta(days=days)
    logs = AdminLog.objects.filter(created_at__lt=cutoff)
    count = logs.count()
    
    # Estimate size (rough calculation)
    size_estimate = count * 500  # ~500 bytes per log entry
    
    deleted_count, _ = logs.delete()
    
    return deleted_count, size_estimate


class AdminActionLogger:
    """
    Context manager for logging admin actions with automatic error handling.
    
    Usage:
        with AdminActionLogger(request.user, 'Driver', driver.id) as logger:
            # Your admin operation here
            driver.is_available = False
            driver.save()
            logger.log_change('is_available', True, False)
    """
    
    def __init__(self, admin_user, content_type, object_id, request=None):
        self.admin_user = admin_user
        self.content_type = content_type
        self.object_id = object_id
        self.request = request
        self.changes = {}
        self.object_description = ''
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Only log successful operations
            self.save()
        return False
    
    def log_change(self, field, old_value, new_value):
        """Record a field change"""
        if old_value != new_value:
            self.changes[field] = {
                'old': str(old_value),
                'new': str(new_value),
            }
    
    def set_description(self, description):
        """Set object description"""
        self.object_description = description
    
    def save(self, action='update'):
        """Save the logged action"""
        return log_admin_action(
            admin_user=self.admin_user,
            action=action,
            content_type=self.content_type,
            object_id=self.object_id,
            object_description=self.object_description,
            changes=self.changes,
            request=self.request,
        )
