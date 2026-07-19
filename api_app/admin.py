from django.contrib import admin

from .models import Bin, Checkpoint, Driver, Notification, Route, Schedule, Vehicle, WasteRequest


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'vehicle_type', 'capacity_kg', 'status', 'last_service_date')
    list_filter = ('status', 'vehicle_type')
    search_fields = ('plate_number',)


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('user', 'vehicle', 'license_number', 'is_available', 'total_trips')
    list_filter = ('is_available',)
    search_fields = ('user__username', 'license_number')


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ('bin_code', 'waste_type', 'status', 'capacity_liters', 'location_address', 'last_emptied')
    list_filter = ('status', 'waste_type')
    search_fields = ('bin_code', 'location_address')


@admin.register(Checkpoint)
class CheckpointAdmin(admin.ModelAdmin):
    list_display = ('name', 'latitude', 'longitude', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    ordering = ('-created_at',)


@admin.register(WasteRequest)
class WasteRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'waste_type', 'status', 'driver', 'dropoff_checkpoint', 'scheduled_date', 'created_at')
    list_filter = ('status', 'waste_type')
    search_fields = ('user__username', 'pickup_address', 'status', 'dropoff_checkpoint__name')
    date_hierarchy = 'created_at'
    raw_id_fields = ('user', 'driver', 'dropoff_checkpoint')


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('id', 'driver', 'vehicle', 'status', 'planned_date', 'total_distance_km')
    list_filter = ('status',)
    date_hierarchy = 'planned_date'


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('zone_name', 'driver', 'vehicle', 'frequency', 'day_of_week', 'start_time', 'is_active')
    list_filter = ('frequency', 'is_active')
    search_fields = ('zone_name',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'title')
    date_hierarchy = 'created_at'