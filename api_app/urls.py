from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminLogViewSet,
    BinViewSet,
    ComplaintViewSet,
    DatabaseBackupViewSet,
    DriverViewSet,
    NotificationViewSet,
    RouteViewSet,
    ScheduleViewSet,
    SystemSettingsViewSet,
    VehicleViewSet,
    WasteRequestViewSet,
)

router = DefaultRouter()
router.register('vehicles',       VehicleViewSet,      basename='vehicle')
router.register('drivers',        DriverViewSet,       basename='driver')
router.register('bins',           BinViewSet,          basename='bin')
router.register('waste-requests', WasteRequestViewSet, basename='waste-request')
router.register('routes',         RouteViewSet,        basename='route')
router.register('schedules',      ScheduleViewSet,     basename='schedule')
router.register('notifications',  NotificationViewSet, basename='notification')
router.register('complaints',     ComplaintViewSet,    basename='complaint')
router.register('admin-logs',     AdminLogViewSet,     basename='admin-log')
router.register('system-settings', SystemSettingsViewSet, basename='system-setting')
router.register('database-backups', DatabaseBackupViewSet, basename='database-backup')

urlpatterns = [
    path('', include(router.urls)),
]