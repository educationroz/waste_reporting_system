from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminLogViewSet,
    AdminUserCreateView,
    AdminUserDeleteView,
    AdminUserUpdateView,
    BinViewSet,
    CheckpointViewSet,
    ComplaintViewSet,
    DatabaseBackupViewSet,
    DriverViewSet,
    NotificationViewSet,
    PushSubscriptionViewSet,
    RouteViewSet,
    ScheduleViewSet,
    SystemSettingsViewSet,
    ThumbnailView,
    VehicleViewSet,
    WasteRequestViewSet,
)

router = DefaultRouter()
router.register('vehicles',       VehicleViewSet,      basename='vehicle')
router.register('drivers',        DriverViewSet,       basename='driver')
router.register('bins',           BinViewSet,          basename='bin')
router.register('waste-requests', WasteRequestViewSet, basename='waste-request')
router.register('checkpoints',     CheckpointViewSet,   basename='checkpoint')
router.register('routes',         RouteViewSet,        basename='route')
router.register('schedules',      ScheduleViewSet,     basename='schedule')
router.register('notifications',  NotificationViewSet, basename='notification')
router.register('push-subscriptions', PushSubscriptionViewSet, basename='push-subscription')
router.register('complaints',     ComplaintViewSet,    basename='complaint')
router.register('admin-logs',     AdminLogViewSet,     basename='admin-log')
router.register('system-settings', SystemSettingsViewSet, basename='system-setting')
router.register('database-backups', DatabaseBackupViewSet, basename='database-backup')

urlpatterns = [
    path('auth/create-admin/', AdminUserCreateView.as_view(), name='create-admin'),
    path('auth/admin/<int:admin_id>/update/', AdminUserUpdateView.as_view(), name='update-admin'),
    path('auth/admin/<int:admin_id>/delete/', AdminUserDeleteView.as_view(), name='delete-admin'),
    path('thumbnail/<str:size>/', ThumbnailView.as_view(), name='thumbnail'),

    path('', include(router.urls)),
]