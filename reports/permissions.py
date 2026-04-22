from rest_framework.permissions import BasePermission


class IsRegularUser(BasePermission):
    """Allow only authenticated regular users (not admins)."""
    message = "Admin accounts cannot submit reports."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_regular_user()
        )


class IsAdminRole(BasePermission):
    """Allow only users with admin role."""
    message = "Only admin users can perform this action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_admin_role()
        )


class IsAdminRoleOrReadOnly(BasePermission):
    """Read: authenticated. Write: admin role only."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.is_admin_role()