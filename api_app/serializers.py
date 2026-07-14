from django.contrib.auth import get_user_model
from rest_framework import serializers # type: ignore

from .models import AdminLog, Bin, Driver, Notification, Route, Schedule, SystemSettings, Vehicle, WasteRequest, Complaint
User = get_user_model()


class UserMinimalSerializer(serializers.ModelSerializer):
    """Lightweight user info embedded in other serializers."""
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'phone', 'role')


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'


class DriverSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='user', write_only=True
    )
    vehicle_detail = VehicleSerializer(source='vehicle', read_only=True)

    class Meta:
        model = Driver
        fields = (
            'id', 'user', 'user_id', 'vehicle', 'vehicle_detail',
            'license_number', 'is_available',
            'current_latitude', 'current_longitude',
            'total_trips', 'created_at',
        )
        read_only_fields = ('total_trips', 'created_at')


class BinSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bin
        fields = '__all__'


class WasteRequestSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    driver_detail = DriverSerializer(source='driver', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    waste_type_display = serializers.CharField(source='get_waste_type_display', read_only=True)

    class Meta:
        model = WasteRequest
        fields = (
            'id', 'user', 'driver', 'driver_detail',
            'waste_type', 'waste_type_display',
            'status', 'status_display',
            'description', 'pickup_address',
            'latitude', 'longitude',
            'photo', 'photo_latitude', 'photo_longitude',
            'scheduled_date', 'completed_at',
            'notes', 'created_at', 'updated_at',
        )
        read_only_fields = ('user', 'completed_at', 'created_at', 'updated_at')

    def validate_photo(self, file):
        """Validate photo file size (max 5MB)."""
        MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
        if file and file.size > MAX_FILE_SIZE:
            raise serializers.ValidationError(
                f"File too large. Maximum size is 5MB, but got {file.size / (1024*1024):.2f}MB"
            )
        return file

    def validate(self, data):
        """Validate latitude/longitude are within valid ranges."""
        if 'latitude' in data and data['latitude'] is not None:
            if not (-90 <= data['latitude'] <= 90):
                raise serializers.ValidationError({'latitude': 'Latitude must be between -90 and 90'})
        
        if 'longitude' in data and data['longitude'] is not None:
            if not (-180 <= data['longitude'] <= 180):
                raise serializers.ValidationError({'longitude': 'Longitude must be between -180 and 180'})
        
        if 'photo_latitude' in data and data['photo_latitude'] is not None:
            if not (-90 <= data['photo_latitude'] <= 90):
                raise serializers.ValidationError({'photo_latitude': 'Latitude must be between -90 and 90'})
        
        if 'photo_longitude' in data and data['photo_longitude'] is not None:
            if not (-180 <= data['photo_longitude'] <= 180):
                raise serializers.ValidationError({'photo_longitude': 'Longitude must be between -180 and 180'})
        
        return data

    # def create(self, validated_data):
    #     validated_data['user'] = self.context['request'].user
    #     return super().create(validated_data)


class RouteSerializer(serializers.ModelSerializer):
    driver_detail = DriverSerializer(source='driver', read_only=True)
    vehicle_detail = VehicleSerializer(source='vehicle', read_only=True)
    waste_request_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=WasteRequest.objects.all(),
        source='waste_requests', required=False,
    )
    bin_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Bin.objects.all(),
        source='bins', required=False,
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Route
        fields = (
            'id', 'driver', 'driver_detail',
            'vehicle', 'vehicle_detail',
            'waste_request_ids', 'bin_ids',
            'status', 'status_display',
            'planned_date', 'started_at', 'completed_at',
            'total_distance_km', 'notes', 'created_at',
        )
        read_only_fields = ('created_at',)


class ScheduleSerializer(serializers.ModelSerializer):
    driver_detail = DriverSerializer(source='driver', read_only=True)
    vehicle_detail = VehicleSerializer(source='vehicle', read_only=True)
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)

    class Meta:
        model = Schedule
        fields = (
            'id', 'zone_name',
            'driver', 'driver_detail',
            'vehicle', 'vehicle_detail',
            'frequency', 'frequency_display',
            'day_of_week', 'start_time',
            'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('created_at', 'updated_at')


class NotificationSerializer(serializers.ModelSerializer):
    related_request_detail = WasteRequestSerializer(
        source='related_request', read_only=True
    )
    type_display = serializers.CharField(
        source='get_notification_type_display', read_only=True
    )

    class Meta:
        model = Notification
        fields = (
            'id', 'user', 'title', 'message',
            'notification_type', 'type_display',
            'is_read', 'related_request', 'related_request_detail',
            'created_at',
        )
        read_only_fields = ('user', 'created_at')


class AdminLogSerializer(serializers.ModelSerializer):
    """Serializer for admin activity logs."""
    admin_user = UserMinimalSerializer(read_only=True)
    admin_user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='admin'),
        source='admin_user',
        write_only=True,
        required=False,
    )
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AdminLog
        fields = (
            'id', 'admin_user', 'admin_user_id', 'action', 'action_display',
            'content_type', 'object_id', 'object_description',
            'changes', 'ip_address', 'user_agent', 'created_at',
        )
        read_only_fields = ('created_at',)


class SystemSettingsSerializer(serializers.ModelSerializer):
    """Serializer for system settings."""
    updated_by = UserMinimalSerializer(read_only=True)
    updated_by_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='admin'),
        source='updated_by',
        write_only=True,
        required=False,
    )

    class Meta:
        model = SystemSettings
        fields = (
            'id', 'key', 'value', 'description',
            'is_sensitive', 'updated_by', 'updated_by_id', 'updated_at',
        )
        read_only_fields = ('updated_at',)

class ComplaintSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    complaint_type_display = serializers.CharField(source='get_complaint_type_display', read_only=True)

    class Meta:
        model = Complaint
        fields = [
            'id', 'user', 'username', 'complaint_type', 'complaint_type_display',
            'subject', 'description', 'photo',
            'status', 'status_display', 'admin_response',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']
        extra_kwargs = {
            'subject': {'required': False},  # auto-filled server-side if omitted
        }

    def validate_photo(self, file):
        MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
        if file and file.size > MAX_FILE_SIZE:
            raise serializers.ValidationError(
                f"File too large. Maximum size is 5MB, but got {file.size / (1024*1024):.2f}MB"
            )
        return file