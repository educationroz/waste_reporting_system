from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminUser(BasePermission):
    """Allow only users with role='admin'."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'admin')


class IsDriverUser(BasePermission):
    """Allow only users with role='driver'."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'driver')


class IsAdminOrReadOnly(BasePermission):
    """Allow admins full access; read-only for authenticated users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role == 'admin'


class IsOwnerOrAdmin(BasePermission):
    """Allow authenticated users to create; owner or admin can edit/delete."""
    
    def has_permission(self, request, view):
        # Allow any authenticated user to create, retrieve list, etc.
        # Object-level permissions (edit/delete) are checked in has_object_permission
        return bool(request.user and request.user.is_authenticated)
    
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'admin':
            return True
        # obj.user for WasteRequest/Notification
        if hasattr(obj, 'user'):
            return obj.user == request.user
        return False