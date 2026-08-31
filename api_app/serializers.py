from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import serializers  # type: ignore

from .models import (
    AdminLog,
    Bin,
    Checkpoint,
    Complaint,
    Driver,
    Notification,
    Route,
    Schedule,
    SystemSettings,
    Vehicle,
    VehicleType,
    WasteRequest,
    WasteRequestPhoto,
)
from .validators import (
    compress_image,
    sanitize_image,
    validate_image_file,
    validate_pdf_file,
)

import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class UserMinimalSerializer(serializers.ModelSerializer):
    """Lightweight user info embedded in other serializers."""
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'phone', 'role')


class VehicleTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = ('id', 'name', 'created_at')
        read_only_fields = ('created_at',)


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
            'license_number', 'license_document', 'is_available',
            'current_latitude', 'current_longitude',
            'total_trips', 'created_at',
        )
        read_only_fields = ('total_trips', 'created_at')

    def validate_license_document(self, file):
        """
        Real content validation, not just a size check: sniffs the actual
        MIME type from the file's bytes (python-magic) and confirms the
        %PDF- magic number, so a renamed .exe/.html can't pass itself off
        as a PDF just by having a .pdf extension.
        """
        if file:
            validate_pdf_file(file)  # raises serializers.ValidationError-compatible
        return file


class BinSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bin
        fields = '__all__'


class CheckpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = Checkpoint
        fields = '__all__'

    def validate(self, data):
        lat = data.get('latitude')
        lng = data.get('longitude')
        if lat is not None and not (-90 <= lat <= 90):
            raise serializers.ValidationError({'latitude': 'Latitude must be between -90 and 90.'})
        if lng is not None and not (-180 <= lng <= 180):
            raise serializers.ValidationError({'longitude': 'Longitude must be between -180 and 180.'})
        return data

class WasteRequestPhotoSerializer(serializers.ModelSerializer):
    """Read-only representation of an extra photo attached to a WasteRequest."""
    class Meta:
        model = WasteRequestPhoto
        fields = ('id', 'photo', 'latitude', 'longitude', 'created_at')
        read_only_fields = fields


class WasteRequestSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)
    driver_detail = DriverSerializer(source='driver', read_only=True)
    dropoff_checkpoint = CheckpointSerializer(read_only=True)
    dropoff_checkpoint_id = serializers.PrimaryKeyRelatedField(
        queryset=Checkpoint.objects.filter(is_active=True),
        source='dropoff_checkpoint',
        write_only=True,
        required=False,
        allow_null=True,
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    waste_type_display = serializers.CharField(source='get_waste_type_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    route_id = serializers.SerializerMethodField()
    route_status = serializers.SerializerMethodField()
    # Extra photos beyond the primary 'photo' field — populated in the view's
    # perform_create() from the 'extra_photos' multipart key, read-only here.
    extra_photos = WasteRequestPhotoSerializer(many=True, read_only=True)

    # Claim-by-email backup: writable on create only (immutable afterwards),
    # and never returned in responses so guest emails don't leak to drivers
    # or admins reading the list endpoint.
    guest_email = serializers.EmailField(
        write_only=True, required=False, allow_blank=True, allow_null=True,
    )
    guest_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True,
    )

    class Meta:
        model = WasteRequest
        fields = (
            'id', 'user', 'driver', 'driver_detail',
            'dropoff_checkpoint', 'dropoff_checkpoint_id',
            'waste_type', 'waste_type_display',
            'status', 'status_display',
            'description', 'pickup_address',
            'latitude', 'longitude',
            'photo', 'photo_latitude', 'photo_longitude',
            'extra_photos',
            'completion_latitude', 'completion_longitude',
            'completion_distance_meters', 'completion_flagged',
            'severity', 'severity_display', 'ml_confidence', 'needs_manual_review',
            'guest_token',  # for guest submissions that can later be claimed
            'guest_email',  # write-only backup claim channel (never exposed in responses)
            'scheduled_date', 'completed_at',
            'notes', 'created_at', 'updated_at',
            'route_id', 'route_status',
        )
        read_only_fields = (
            'user', 'completed_at', 'created_at', 'updated_at',
            'severity', 'ml_confidence', 'needs_manual_review',
            'completion_latitude', 'completion_longitude',
            'completion_distance_meters', 'completion_flagged',
            # Admin-only transitions. create is AllowAny, so leaving these
            # writable let any anonymous visitor forge {"status": "completed",
            # "driver": <id>} and skip the whole admin assignment + GPS
            # completion pipeline. Updates must go through the dedicated
            # update_status / assign_driver actions.
            'status', 'driver',
        )

    def get_route_id(self, obj):
        route = obj.routes.order_by('-created_at').first()
        return route.id if route else None

    def get_route_status(self, obj):
        route = obj.routes.order_by('-created_at').first()
        return route.get_status_display() if route else None

    def validate_photo(self, file):
        """
        Full defence-in-depth pipeline for the uploaded photo:
          1. validate_image_file — size cap + real MIME sniff (python-magic)
             + Pillow structural verification. Rejects a renamed non-image
             outright, before it ever touches the ML model or disk.
          2. sanitize_image — fully decodes and re-encodes the image from
             scratch, stripping any bytes appended after the real image
             data (the classic "valid JPEG + payload glued on" polyglot
             trick). The ML model reads this clean copy, never the
             original upload.
          3. Run the ML gatekeeper on the sanitized copy — NOW ASYNC (see
             below) so uploads don't freeze the web worker on CPU inference.
          4. compress_image — resize/re-encode for storage after the ML
             check ran, so the classifier always sees full quality.

        Async ML behaviour:
        - The fast, always-synchronous steps (validate/sanitize/compress)
          still run here in the request.
        - Inference is scheduled on the background pool (api_app/tasks.py).
          We wait up to ``ML_FAST_PATH_TIMEOUT`` seconds for it: if it
          resolves in time, a *confidently* non-waste photo is hard-rejected
          here, and a confident positive attaches its severity/confidence to
          the row immediately.
        - If inference is slower than the timeout (heavy load / cold model),
          the request is NOT blocked: we default the row to
          ``needs_manual_review=True`` and stash the sanitized image bytes on
          the serializer so the view can schedule a background classification
          that fills in the real severity/confidence right after the save.
        """
        if not file:
            return file

        validate_image_file(file)  # raises on spoofed/corrupt/oversized files
        clean_file = sanitize_image(file)

        # Fast-path inference with a bounded wait.
        result = None
        try:
            from io import BytesIO

            from .tasks import submit
            from ml_models.waste_classifier.inference import predict_waste

            bytes_io = BytesIO()
            clean_file.seek(0)
            for chunk in iter(lambda: clean_file.read(65536), b''):
                bytes_io.write(chunk)
            image_bytes = bytes_io.getvalue()
            clean_file.seek(0)

            timeout = getattr(settings, 'ML_FAST_PATH_TIMEOUT', 1.5)
            future = submit(predict_waste, BytesIO(image_bytes))
            if timeout > 0:
                try:
                    result = future.result(timeout=timeout)
                except BaseException:
                    # Inference did not finish within the fast-path window —
                    # don't block the request; defer to background update.
                    result = None
            else:
                result = future.result()
        except Exception:
            # Model missing / import error / any ML failure must not break
            # citizen reporting. Flag for manual review and move on.
            logger.exception('[ML] fast-path inference unavailable; flagging for review.')
            result = None

        if result is not None:
            if not result.get('is_waste'):
                raise serializers.ValidationError(
                    "This doesn't look like waste. Please upload a valid waste photo."
                )

        # Default pending state until the background task fills in the truth.
        # result is None exactly when inference deferred (timeout/error) —
        # that is the only case needing a background classification.
        self._ml_result = result
        self._ml_bytes = image_bytes if result is None else None

        clean_file.seek(0)
        compressed_file = compress_image(clean_file)  # shrink for storage, ML already ran
        return compressed_file

    def validate(self, data):
        """Validate latitude/longitude are within valid ranges, and attach ML result."""
        if 'latitude' in data and data['latitude'] is not None:
            if not (-90 <= data['latitude'] <= 90):
                raise serializers.ValidationError({'latitude': 'Latitude must be between -90 and 90'})

        if 'longitude' in data and data['longitude'] is not None:
            if not (-180 <= data['longitude'] <= 180):
                raise serializers.ValidationError({'longitude': 'Longitude must be between -180 and 180'})

        if 'guest_email' in data and data['guest_email'] in (None, ''):
            # Client sent an empty string — normalize to NULL so the db_index
            # stays usable and unclaimed rows aren't stuffed with blanks.
            data.pop('guest_email')

        if 'photo_latitude' in data and data['photo_latitude'] is not None:
            if not (-90 <= data['photo_latitude'] <= 90):
                raise serializers.ValidationError({'photo_latitude': 'Latitude must be between -90 and 90'})

        if 'photo_longitude' in data and data['photo_longitude'] is not None:
            if not (-180 <= data['photo_longitude'] <= 180):
                raise serializers.ValidationError({'photo_longitude': 'Longitude must be between -180 and 180'})

        # Attach ML gatekeeper result (set in validate_photo above) so it gets saved.
        # When inference deferred to the background (pending), default to
        # "needs_manual_review" so an admin catches anything inconclusive before
        # the async result lands.
        ml_result = getattr(self, '_ml_result', None)
        if ml_result:
            data['severity'] = ml_result['severity']
            data['ml_confidence'] = ml_result['confidence']
            data['needs_manual_review'] = ml_result['needs_manual_review']
        else:
            data['severity'] = None
            data['ml_confidence'] = None
            data['needs_manual_review'] = True

        return data

    # def create(self, validated_data):
    #     validated_data['user'] = self.context['request'].user
    #     return super().create(validated_data)

    def update(self, instance, validated_data):
        # guest_token/guest_email identify how the row may be claimed; once set
        # at creation they are immutable — an authenticated user must NOT be
        # able to re-point a request at their own token/email via PATCH.
        validated_data.pop('guest_token', None)
        validated_data.pop('guest_email', None)
        return super().update(instance, validated_data)


class WasteRequestMinimalSerializer(serializers.ModelSerializer):
    """
    Lightweight WasteRequest representation for embedding inside other
    serializers (e.g. NotificationSerializer.related_request_detail).

    Deliberately does NOT include:
      - guest_token: internal claim credential — leaking it would let
        anyone who can see a notification steal/claim someone else's
        guest-submitted request via claim_guest_requests.
      - driver_detail / dropoff_checkpoint / extra_photos: these pull in
        DriverSerializer -> VehicleSerializer and a full photo list, which
        is exactly the nested chain that turns "list my notifications"
        into hundreds of queries for a user with many notifications.

    Only the fields a notification actually needs to show/link to the
    related request are included here.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    waste_type_display = serializers.CharField(source='get_waste_type_display', read_only=True)

    class Meta:
        model = WasteRequest
        fields = (
            'id', 'status', 'status_display',
            'waste_type', 'waste_type_display',
            'pickup_address', 'created_at',
        )
        read_only_fields = fields


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
    related_request_detail = WasteRequestMinimalSerializer(
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
        read_only_fields = [
            'user', 'created_at', 'updated_at',
            # Complaint owners may not self-resolve: status/admin_response are
            # moderated by admins (ComplaintViewSet.update_status). Leaving them
            # writable let the reporter PATCH {"status": "completed"} and forge
            # an official resolution.
            'status', 'admin_response',
        ]
        extra_kwargs = {
            'subject': {'required': False},  # auto-filled server-side if omitted
        }

    def validate_photo(self, file):
        """
        Same defence-in-depth pipeline as WasteRequestSerializer.validate_photo,
        minus the ML gatekeeper step (complaints don't get auto-classified).
        Still compressed before storage for the same reason — complaint
        photos come from the same phone cameras and hit the same map/list
        display surfaces as waste-request photos.
        """
        if not file:
            return file
        validate_image_file(file)
        clean_file = sanitize_image(file)
        return compress_image(clean_file)