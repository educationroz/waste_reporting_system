import io
import math
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from .backup_utils import BACKUP_DIR as BACKUP_DIR_FOR_UPLOADS
from .backup_utils import verify_backup_file
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.exceptions import InvalidChannelLayerError
from channels.layers import get_channel_layer # type: ignore
from rest_framework import filters, status, viewsets # type: ignore
from rest_framework.decorators import action # type: ignore
from rest_framework.permissions import AllowAny, IsAuthenticated # type: ignore
from rest_framework.response import Response # type: ignore
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser # type: ignore
from .models import (
    AdminLog, Bin, Checkpoint, Complaint, Driver, Notification, Route, Schedule,
    SystemSettings, Vehicle, WasteRequest, WasteRequestPhoto,
)
from .permissions import IsAdminOrReadOnly, IsAdminUser, IsOwnerOrAdmin
from .serializers import (
    AdminLogSerializer,
    BinSerializer,
    CheckpointSerializer,
    DriverSerializer,
    NotificationSerializer,
    RouteSerializer,
    ScheduleSerializer,
    SystemSettingsSerializer,
    VehicleSerializer,
    WasteRequestSerializer,
    ComplaintSerializer,
)
from .backup_utils import (
    BackupError,
    BACKUP_DIR as BACKUP_DIR_FOR_UPLOADS,
    create_backup,
    list_backups,
    resolve_backup_path,
    restore_backup,
)


try:
    CHANNEL_LAYER = get_channel_layer()
except InvalidChannelLayerError:
    CHANNEL_LAYER = None

User = get_user_model()

import logging
logger = logging.getLogger('notif_debug')
logging.basicConfig(level=logging.INFO)
backup_logger = logging.getLogger('backup')  # same logger name as backup_utils.py, so backup-related
                                              # log lines from both files end up under one logger/handler
# ── Completion GPS verification ──────────────────────────────────────────────
# Driver ले "Completed" mark गर्ने बेला उनको GPS pickup location भन्दा यो
# थ्रेसहोल्ड (मिटरमा) भन्दा टाढा भए suspicious मानिन्छ — admin लाई flag देखाइन्छ।
COMPLETION_DISTANCE_THRESHOLD_METERS = 500


def _haversine_meters(lat1, lng1, lat2, lng2):
    """Distance in meters between two lat/lng points (Haversine formula)."""
    import math
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Same-location request grouping ───────────────────────────────────────────
# Multiple people often report the SAME pile of waste from slightly different
# spots (GPS drift alone is easily 10-20m). Those are one job for the driver,
# so assigning or completing one request cascades to its neighbours within this
# radius. Kept well under COMPLETION_DISTANCE_THRESHOLD_METERS so a genuinely
# different pickup down the road is never swallowed into the group.
SAME_LOCATION_RADIUS_METERS = 100

# Only requests still waiting for work get pulled into a group; anything already
# completed/cancelled is left exactly as it is.
GROUPABLE_STATUSES = ('pending', 'assigned', 'in_progress')


def _request_coords(waste_request):
    """Best-available (lat, lng) for a request, falling back to the photo EXIF."""
    lat = waste_request.latitude if waste_request.latitude is not None else waste_request.photo_latitude
    lng = waste_request.longitude if waste_request.longitude is not None else waste_request.photo_longitude
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _same_location_siblings(waste_request):
    """
    Other active requests reporting the same spot as `waste_request`.

    Returns a list (never a queryset) so callers can safely mutate the rows.
    Returns [] when the request has no usable coordinates — without a location
    we cannot prove anything is a sibling, and silently grouping by address
    text would be far too eager.
    """
    origin = _request_coords(waste_request)
    if origin is None:
        return []
    origin_lat, origin_lng = origin

    # Cheap bounding-box prefilter so we don't haversine the whole table;
    # ~1 degree of latitude is 111.32km, and longitude shrinks with latitude.
    lat_delta = SAME_LOCATION_RADIUS_METERS / 111_320
    cos_lat = math.cos(math.radians(origin_lat))
    lng_delta = SAME_LOCATION_RADIUS_METERS / (111_320 * cos_lat) if cos_lat else 180

    candidates = WasteRequest.objects.filter(
        status__in=GROUPABLE_STATUSES,
        is_deleted=False,
    ).exclude(pk=waste_request.pk).filter(
        Q(latitude__gte=origin_lat - lat_delta, latitude__lte=origin_lat + lat_delta,
          longitude__gte=origin_lng - lng_delta, longitude__lte=origin_lng + lng_delta)
        | Q(latitude__isnull=True, photo_latitude__gte=origin_lat - lat_delta,
            photo_latitude__lte=origin_lat + lat_delta,
            photo_longitude__gte=origin_lng - lng_delta,
            photo_longitude__lte=origin_lng + lng_delta)
    )

    siblings = []
    for candidate in candidates:
        coords = _request_coords(candidate)
        if coords is None:
            continue
        if _haversine_meters(origin_lat, origin_lng, coords[0], coords[1]) <= SAME_LOCATION_RADIUS_METERS:
            siblings.append(candidate)
    return siblings


def _log_admin_action(request, action_type, content_type, obj, description=''):
    """
    Create an AdminLog entry. Any authenticated user's tracked action gets
    logged here — admin, driver, or regular user.
    """
    if not request.user.is_authenticated:
        return
    AdminLog.objects.create(
        admin_user=request.user,
        action=action_type,
        content_type=content_type,
        object_id=getattr(obj, 'id', None),
        object_description=description or str(obj),
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
    )


def _push_ws_notification(notification):
    """
    Push a just-created Notification over its owner's personal WebSocket
    group (NotificationConsumer, group name 'notifications_user_{id}').

    This is the piece that was missing everywhere: Notification.objects.create()
    only writes to the DB. The base.html WebSocket client listens for a live
    'notification' event on this group to pop the toast/badge — without this
    group_send, nothing ever arrives over the socket and the notification only
    shows up after a manual refresh/poll.
    """
    group_name = f'notifications_user_{notification.user_id}'
    logger.info(
        f'[NOTIF PUSH] attempting push: user_id={notification.user_id} '
        f'group={group_name} channel_layer_is_none={CHANNEL_LAYER is None} '
        f'title={notification.title!r}'
    )
    if CHANNEL_LAYER is None or not notification.user_id:
        logger.warning('[NOTIF PUSH] skipped — no channel layer or no user_id')
        return
    async_to_sync(CHANNEL_LAYER.group_send)(
        group_name,
        {
            'type': 'send_notification',
            'title': notification.title,
            'message': notification.message,
            'notification_type': notification.notification_type,
        }
    )
    logger.info(f'[NOTIF PUSH] group_send completed for group={group_name}')


def _create_notification(user, title, message, notification_type='info', related_request=None):
    """
    Single entry point for creating a Notification: writes the DB row AND
    pushes it live over the WebSocket, so every call site gets both for free
    instead of relying on each caller to remember the group_send.
    """
    # Prevent spamming the same notification repeatedly to the same user
    recent_cutoff = timezone.now() - timedelta(seconds=30)
    exists = Notification.objects.filter(
        user=user,
        title=title,
        message=message,
        created_at__gte=recent_cutoff,
    ).exists()
    if exists:
        logger.info(f"[NOTIF SKIP] duplicate notification skipped for user={user.id} title={title!r}")
        return None

    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        related_request=related_request,
    )
    _push_ws_notification(notification)
    return notification


def _notify_driver(driver, title, message, notification_type='info', related_request=None):
    """
    Create a Notification for a driver's linked user account.
    This is what makes the toast/badge show up on the driver dashboard —
    base.html's notifications WebSocket already listens for any Notification
    created for the logged-in user; it just needed the live group_send too
    (see _create_notification / _push_ws_notification above), since before
    this it was never being pushed live for anyone, driver or not.
    """
    if not driver or not driver.user_id:
        return
    _create_notification(
        user=driver.user,
        title=title,
        message=message,
        notification_type=notification_type,
        related_request=related_request,
    )


def _notify_all_users(title, message, notification_type='info'):
    """
    Broadcast a Notification (DB row + live WS push) to every active
    account — admin, driver, and regular user — so everyone hears about
    checkpoint changes and their map can react to it live.
    """
    User = get_user_model()
    for user in User.objects.filter(is_active=True):
        _create_notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
        )
def _notify_admins(title, message, notification_type='info'):
    """
    Notify every admin account (DB row + live WS push each). Used for
    events admins need to react to immediately — e.g. a new complaint
    being filed — so the admin sidebar's complaints badge can update
    live via WebSocket instead of only refreshing on next page load.
    """
    User = get_user_model()
    for admin_user in User.objects.filter(is_active=True, role='admin'):
        _create_notification(
            user=admin_user,
            title=title,
            message=message,
            notification_type=notification_type,
        )

class DatabaseBackupViewSet(viewsets.GenericViewSet):
    """Create, list, download, restore, and delete JSON database backups."""
    permission_classes = [IsAuthenticated, IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @action(detail=False, methods=['get'])
    def history(self, request):
        return Response(list_backups())

    @action(detail=False, methods=['post'])
    def backup(self, request):
        try:
            result = create_backup()
        except BackupError as exc:
            # create_backup() wraps the real exception in its BackupError
            # message (e.g. "Backup failed: <raw exc>") — that detail is
            # only useful to us, not the client.
            backup_logger.exception('Database backup creation failed: %s', exc)
            return Response(
                {'error': 'Backup failed. Please check server logs or try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        _log_admin_action(request, 'other', 'DatabaseBackup', None, f"Created backup {result['file_name']}")
        return Response(result)

    @action(detail=False, methods=['get'])
    def download(self, request):
        file_name = request.query_params.get('file_name')
        try:
            backup_path = resolve_backup_path(file_name)
        except BackupError as exc:
            # resolve_backup_path's BackupError messages are already
            # curated/safe ("not found" / "invalid location") — no raw
            # exception internals to strip here.
            backup_logger.warning('Backup download rejected: %s', exc)
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return FileResponse(
            backup_path.open('rb'),
            as_attachment=True,
            filename=backup_path.name,
            content_type='application/json',
        )

    @action(detail=False, methods=['delete'])
    def delete(self, request):
        file_name = request.query_params.get('file_name')
        try:
            backup_path = resolve_backup_path(file_name)
        except BackupError as exc:
            backup_logger.warning('Backup delete rejected: %s', exc)
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        backup_path.unlink(missing_ok=True)
        (backup_path.parent / f'{backup_path.name}.sha256').unlink(missing_ok=True)
        _log_admin_action(request, 'delete', 'DatabaseBackup', None, f'Deleted backup {file_name}')
        return Response({'message': f'Backup {file_name} deleted successfully.'})

    @action(detail=False, methods=['post'])
    def restore(self, request):
        confirm = request.data.get('confirm') or request.POST.get('confirm')
        if str(confirm).lower() != 'true':
            return Response(
                {'error': 'Restore is destructive. Confirm with confirm=true after notifying the user.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES.get('backup_file')
        if not uploaded_file:
            return Response({'error': 'backup_file is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if not uploaded_file.name.endswith('.json'):
            return Response({'error': 'Only .json backup files are supported.'}, status=status.HTTP_400_BAD_REQUEST)

        # Write to BACKUP_DIR first so restore_backup() can operate on a
        # real Path. Nothing here has been verified yet.
        backup_path = BACKUP_DIR_FOR_UPLOADS / uploaded_file.name
        try:
            with backup_path.open('wb') as backup_file:
                for chunk in uploaded_file.chunks():
                    backup_file.write(chunk)
        except OSError as exc:
            backup_logger.exception('Failed writing uploaded backup file: %s', exc)
            return Response(
                {'error': 'Could not save the uploaded file. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            # restore_backup() calls verify_backup_file() as its very first
            # step — flush/loaddata never runs against an unverified file.
            # It also auto-snapshots current state first and attempts
            # auto-recovery if loaddata fails partway through.
            result = restore_backup(backup_path)
        except BackupError as exc:
            msg = str(exc)
            backup_logger.exception('Restore failed for %r requested by %s: %s',
                                     uploaded_file.name, request.user.username, msg)

            # Pre-flush validation failures (bad JSON / not a fixture / empty
            # file) are safe, curated messages — nothing was touched, so it's
            # fine and helpful to show them directly.
            if 'AUTOMATIC RECOVERY FAILED' in msg:
                # Worst case: flush ran, loaddata failed, AND recovery of the
                # pre-restore snapshot also failed. This is the one case
                # where raw exception text must never reach the client, but
                # the admin genuinely needs to know the DB may be empty.
                return Response(
                    {'error': 'Restore failed and automatic recovery of your previous data also '
                              'failed. The database may be in an inconsistent state — contact a '
                              'system administrator immediately. A safety backup was taken before '
                              'this restore and is available in the backups directory; check server '
                              'logs for its exact filename.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            if 'automatically recovered' in msg:
                return Response(
                    {'error': 'Restore failed, but your previous data was automatically recovered — '
                              'no data was lost. Please verify the backup file and try again.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if msg.startswith('Could not create safety backup'):
                return Response(
                    {'error': 'Could not safely start the restore (a pre-restore snapshot could not '
                              'be created), so nothing was changed. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            # Pre-flush validation failure — safe to show verbatim.
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        # `flush` deletes every row (including the currently logged-in user's),
        # then `loaddata` reinserts everyone from the backup with fresh primary
        # keys. request.user is still the pre-restore in-memory object, so its
        # old pk may no longer exist — re-fetch by username instead, and treat
        # logging as best-effort so a logging hiccup never masks a successful
        # restore.
        try:
            current_user = type(request.user).objects.filter(username=request.user.username).first()
            if current_user:
                AdminLog.objects.create(
                    admin_user=current_user,
                    action='other',
                    content_type='DatabaseBackup',
                    object_id=None,
                    object_description=f"Restored from backup {result['restored_file']} "
                                        f"({result['record_count']} records; safety copy: {result['safety_backup']})",
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                )
        except Exception as log_exc:
            backup_logger.warning('Post-restore admin-log write failed: %s', log_exc)

        return Response({
            'message': f"Backup {result['restored_file']} restored successfully.",
            'restored_file': result['restored_file'],
            'record_count': result['record_count'],
            'safety_backup': result['safety_backup'],
        })

class VehicleViewSet(viewsets.ModelViewSet):
    """CRUD for vehicles. Admins manage, all authenticated users read."""
    queryset = Vehicle.objects.prefetch_related('assigned_drivers__user', 'routes').order_by('-created_at')
    serializer_class = VehicleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['plate_number', 'vehicle_type', 'status']
    ordering_fields = ['created_at', 'status']

    def perform_create(self, serializer):
        vehicle = serializer.save()
        _log_admin_action(self.request, 'create', 'Vehicle', vehicle, f'Added vehicle {vehicle.plate_number}')

    def perform_update(self, serializer):
        vehicle = serializer.save()
        _log_admin_action(self.request, 'update', 'Vehicle', vehicle, f'Updated vehicle {vehicle.plate_number}')

    def perform_destroy(self, instance):
        _log_admin_action(self.request, 'delete', 'Vehicle', instance, f'Removed vehicle {instance.plate_number}')
        instance.delete()

    @action(detail=False, methods=['get'])
    def available(self, request):
        """GET /api/vehicles/available/ — list available vehicles only."""
        qs = Vehicle.objects.filter(status='available').prefetch_related('assigned_drivers__user', 'routes')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class DriverViewSet(viewsets.ModelViewSet):
    """
    CRUD for driver profiles.
    Drivers can update their own location. Admins manage all.
    """
    queryset = Driver.objects.select_related('user', 'vehicle').all()
    serializer_class = DriverSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__username', 'license_number']
    # NEW: needed so the license_document PDF (and any other file field)
    # can be uploaded via multipart/form-data on PATCH — without this,
    # DriverViewSet only accepted JSON bodies and a file upload would 400.
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_create(self, serializer):
        driver = serializer.save()
        _log_admin_action(self.request, 'create', 'Driver', driver, f'Registered driver {driver.user.username}')

    def perform_update(self, serializer):
        driver = serializer.save()
        _log_admin_action(self.request, 'update', 'Driver', driver, f'Updated driver {driver.user.username}')

    def destroy(self, request, *args, **kwargs):
        """Delete the driver profile and the linked auth user together."""
        driver = self.get_object()
        user = driver.user
        _log_admin_action(request, 'delete', 'Driver', driver, f'Removed driver {user.username}')

        with transaction.atomic():
            user.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def toggle_availability(self, request, pk=None):
        """PATCH /api/drivers/{id}/toggle_availability/ — driver toggles their own is_available."""
        driver = self.get_object()
        if request.user.role != 'admin' and driver.user != request.user:
            return Response(
                {'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN
            )
        driver.is_available = not driver.is_available
        driver.save(update_fields=['is_available'])

        _log_admin_action(
            request, 'update', 'Driver', driver,
            f'{driver.user.username} availability set to {driver.is_available}'
        )
        return Response(DriverSerializer(driver).data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_location(self, request, pk=None):
        """PATCH /api/drivers/{id}/update_location/ — driver updates GPS location."""
        driver = self.get_object()
        # Only the driver themselves or admin can update location
        if request.user.role != 'admin' and driver.user != request.user:
            return Response(
                {'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN
            )
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        if lat is None or lng is None:
            return Response(
                {'error': 'latitude and longitude required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        driver.current_latitude = lat
        driver.current_longitude = lng
        driver.save(update_fields=['current_latitude', 'current_longitude'])

        if CHANNEL_LAYER is not None:
            async_to_sync(CHANNEL_LAYER.group_send)(
                'driver_locations',
                {
                    'type': 'driver_location_update',
                    'driver_id': driver.id,
                    'latitude': str(lat),
                    'longitude': str(lng),
                }
            )
        return Response({'message': 'Location updated.', 'latitude': lat, 'longitude': lng})



class BinViewSet(viewsets.ModelViewSet):
    """CRUD for waste bins. Admins write, all authenticated users read."""
    queryset = Bin.objects.prefetch_related('routes').order_by('-created_at')
    serializer_class = BinSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['bin_code', 'waste_type', 'status', 'location_address']
    ordering_fields = ['created_at', 'status']

    def perform_create(self, serializer):
        bin_obj = serializer.save()
        _log_admin_action(self.request, 'create', 'Bin', bin_obj, f'Added bin {bin_obj.bin_code}')

    def perform_update(self, serializer):
        bin_obj = serializer.save()
        _log_admin_action(self.request, 'update', 'Bin', bin_obj, f'Updated bin {bin_obj.bin_code}')

    def perform_destroy(self, instance):
        _log_admin_action(self.request, 'delete', 'Bin', instance, f'Removed bin {instance.bin_code}')
        instance.delete()

    @action(detail=False, methods=['get'])
    def full_bins(self, request):
        """GET /api/bins/full_bins/ — bins that are full or overflowing."""
        qs = Bin.objects.filter(status__in=['full', 'overflow']).prefetch_related('routes')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class CheckpointViewSet(viewsets.ModelViewSet):
    """Admin-managed designated drop-off locations."""
    queryset = Checkpoint.objects.all().order_by('-created_at')
    serializer_class = CheckpointSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [AllowAny()]
        return [IsAuthenticated(), IsAdminUser()]

    def perform_create(self, serializer):
        # Standard create path used by non-API callers — keep minimal.
        serializer.save()

    def create(self, request, *args, **kwargs):
        # Full create flow for API: include idempotency/dedupe info in response
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        name = data.get('name')
        lat = data.get('latitude')
        lng = data.get('longitude')

        deduped = False
        existing_id = None

        if lat is not None and lng is not None:
            tol = Decimal('0.000001')
            recent = Checkpoint.objects.filter(
                name=name,
                latitude__gte=lat - tol,
                latitude__lte=lat + tol,
                longitude__gte=lng - tol,
                longitude__lte=lng + tol,
            ).order_by('-created_at').first()
            if recent:
                checkpoint = recent
                deduped = True
                existing_id = recent.id
            else:
                checkpoint = serializer.save()
        else:
            checkpoint = serializer.save()

        _log_admin_action(request, 'create', 'Checkpoint', checkpoint, f'Created checkpoint {checkpoint.name}')
        # Only notify users when a new checkpoint was actually created
        if not deduped:
            _notify_all_users(
                title='New Checkpoint Added',
                message=f'A new checkpoint "{checkpoint.name}" is now available on the map.',
                notification_type='info',
            )

        out = CheckpointSerializer(checkpoint, context={'request': request}).data
        out.update({'deduped': deduped})
        if deduped:
            out.update({'existing_checkpoint_id': existing_id})

        return Response(out, status=status.HTTP_200_OK)

    def perform_update(self, serializer):
        checkpoint = serializer.save()
        _log_admin_action(self.request, 'update', 'Checkpoint', checkpoint, f'Updated checkpoint {checkpoint.name}')
        _notify_all_users(
            title='Checkpoint Updated',
            message=f'Checkpoint "{checkpoint.name}" was moved or edited — the map has been refreshed.',
            notification_type='info',
        )

    def perform_destroy(self, instance):
        _log_admin_action(self.request, 'delete', 'Checkpoint', instance, f'Deleted checkpoint {instance.name}')
        _notify_all_users(
            title='Checkpoint Removed',
            message=f'Checkpoint "{instance.name}" has been removed.',
            notification_type='warning',
        )
        instance.delete()
        
class AdminUserCreateView(APIView):
    """POST /api/auth/create-admin/ — superadmin creates a new admin account."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email', '')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')

        if not username or not password:
            return Response(
                {'error': 'username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username=username).exists():
            return Response(
                {'error': 'That username is already taken.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admin_user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        admin_user.role = 'admin'
        admin_user.is_staff = True
        admin_user.save(update_fields=['role', 'is_staff'])

        _log_admin_action(
            request, 'create', 'AdminUser', admin_user,
            f'Created admin account {admin_user.username}'
        )

        return Response({
            'id': admin_user.id,
            'username': admin_user.username,
            'email': admin_user.email,
            'first_name': admin_user.first_name,
            'last_name': admin_user.last_name,
            'role': admin_user.role,
        }, status=status.HTTP_201_CREATED)


class AdminUserUpdateView(APIView):
    """PATCH/PUT /api/auth/admin/{admin_id}/update/ — edit an admin account."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def patch(self, request, admin_id):
        try:
            admin_user = User.objects.get(id=admin_id, role='admin')
        except User.DoesNotExist:
            return Response({'error': 'Admin user not found.'}, status=status.HTTP_404_NOT_FOUND)

        for field in ('first_name', 'last_name', 'email'):
            if field in request.data:
                setattr(admin_user, field, request.data[field])

        new_password = request.data.get('password')
        if new_password:
            admin_user.set_password(new_password)

        admin_user.save()

        _log_admin_action(
            request, 'update', 'AdminUser', admin_user,
            f'Updated admin account {admin_user.username}'
        )

        return Response({
            'id': admin_user.id,
            'username': admin_user.username,
            'email': admin_user.email,
            'first_name': admin_user.first_name,
            'last_name': admin_user.last_name,
            'role': admin_user.role,
        })

    def put(self, request, admin_id):
        return self.patch(request, admin_id)


class AdminUserDeleteView(APIView):
    """DELETE /api/auth/admin/{admin_id}/delete/ — remove an admin account."""
    permission_classes = [IsAuthenticated, IsAdminUser]

    def delete(self, request, admin_id):
        try:
            admin_user = User.objects.get(id=admin_id, role='admin')
        except User.DoesNotExist:
            return Response({'error': 'Admin user not found.'}, status=status.HTTP_404_NOT_FOUND)

        if admin_user.id == request.user.id:
            return Response(
                {'error': "You can't delete your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = admin_user.username
        _log_admin_action(request, 'delete', 'AdminUser', admin_user, f'Deleted admin account {username}')
        admin_user.delete()

        return Response(
            {'message': f'Admin {username} deleted successfully.'},
            status=status.HTTP_204_NO_CONTENT,
        )

class WasteRequestViewSet(viewsets.ModelViewSet):
    """
    Waste pickup requests.
    - Anonymous (guest): can create a request only (no login required to report garbage).
    - Regular users: create + view own requests only.
    - Drivers: view assigned requests; update status.
    - Admins: full access + assign drivers.
    """
    serializer_class = WasteRequestSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['status', 'waste_type', 'pickup_address', 'user__username']
    ordering_fields = ['created_at', 'scheduled_date', 'status']

    def get_permissions(self):
        """
        create (submitting a new pickup request) chai guest (login nagareko) lai pani
        khula rakhne.
        assign_driver / update_status chai driver/admin le use garne action ho —
        yaha IsOwnerOrAdmin apply garda driver "owner" nabhako le 403 aauthyo,
        tesैle yi lai IsAuthenticated matra rakheर, role-check function bhitra nai
        (already existing) garne.
        soft_delete / restore chai request ko malik (owner) le afैle Recycle Bin
        ma sarne / restore garne action ho, tesैle IsOwnerOrAdmin nai lagau —
        owner ra admin duवैले use garna paaun.
        Baaki (list/retrieve/update/delete) chai login + ownership check required nai.
        """
        if self.action == 'create':
            return [AllowAny()]
        if self.action in ('assign_driver', 'update_status'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOwnerOrAdmin()]

    def get_queryset(self):
        user = self.request.user
        base_qs = WasteRequest.objects.select_related(
            'user',
            'driver',
            'driver__user',
            'driver__vehicle',
        ).prefetch_related('extra_photos')

        # Anonymous user le create bahek arko kunai action hit garyo bhane
        # (theoretically hunu hudaina kina ki get_permissions le block garcha),
        # safety net ko lagi khali queryset return garne.
        if not user.is_authenticated:
            return base_qs.none()

        if user.role == 'admin':
            qs = base_qs
        elif user.role == 'driver':
            qs = base_qs.filter(driver__user=user)
        else:
            qs = base_qs.filter(user=user)

        # Recycle Bin ma sareko (soft-deleted) request haru default LIST
        # (dashboard/list) ma nadekhine. Detail-level actions (restore,
        # soft_delete, destroy, retrieve, ...) ma chai yo filter LAGAUNE HOINA —
        # natra get_object() le Recycle Bin ma bhaisakeko item nai "list" bhitra
        # nadekheर 404 dinthyo (Restore / Delete Forever button haru fail huनु
        # ko karan yehi thiyo).
        if self.action == 'list':
            include_deleted = self.request.query_params.get('include_deleted', '').lower() == 'true'
            only_deleted = self.request.query_params.get('deleted_only', '').lower() == 'true'
            if only_deleted:
                qs = qs.filter(is_deleted=True)
            elif not include_deleted:
                qs = qs.filter(is_deleted=False)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        waste_request = serializer.save(user=user)

        # Frontend le 'extra_photos' key ma pahilo photo bahekका baँki sabai
        # photo haru pathaउँछ — tiनीहरूलाई WasteRequestPhoto table ma save garne.
        # GPS chai frontend le 'extra_photos_latitude' / 'extra_photos_longitude'
        # array haru pathayo bhane (same index alignment), tyo pani save garne —
        # natra photo_latitude/longitude sabै NULL nai rahanchha.
        extra_files = self.request.FILES.getlist('extra_photos')
        extra_lats = self.request.POST.getlist('extra_photos_latitude')
        extra_lngs = self.request.POST.getlist('extra_photos_longitude')

        for idx, photo_file in enumerate(extra_files):
            lat = extra_lats[idx] if idx < len(extra_lats) and extra_lats[idx] else None
            lng = extra_lngs[idx] if idx < len(extra_lngs) and extra_lngs[idx] else None
            WasteRequestPhoto.objects.create(
                request=waste_request,
                photo=photo_file,
                latitude=lat,
                longitude=lng,
            )

        if user:
            total_photos = len(extra_files) + (1 if waste_request.photo else 0)
            photo_note = f' with {total_photos} photo(s)' if total_photos else ''
            _log_admin_action(
                self.request, 'create', 'WasteRequest', waste_request,
                f'{user.username} submitted pickup request #{waste_request.id}{photo_note}'
            )

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def assign_driver(self, request, pk=None):
        """PATCH /api/waste-requests/{id}/assign_driver/ — admin assigns driver."""
        if request.user.role != 'admin':
            return Response({'error': 'Admin only.'}, status=status.HTTP_403_FORBIDDEN)
        waste_request = self.get_object()
        driver_id = request.data.get('driver_id')
        try:
            driver = Driver.objects.select_related('user').get(id=driver_id)
        except Driver.DoesNotExist:
            return Response({'error': 'Driver not found.'}, status=status.HTTP_404_NOT_FOUND)

        waste_request.driver = driver
        waste_request.status = 'assigned'
        waste_request.save(update_fields=['driver', 'status'])

        # Everyone reporting this same spot is really one job, so hand the
        # whole cluster to the same driver instead of dispatching several
        # drivers to the same pile of waste.
        siblings = _same_location_siblings(waste_request)
        for sibling in siblings:
            sibling.driver = driver
            sibling.status = 'assigned'
            sibling.save(update_fields=['driver', 'status'])

        grouped_note = f' (+{len(siblings)} same-location request(s))' if siblings else ''
        _log_admin_action(
            request, 'assign', 'WasteRequest', waste_request,
            f'Assigned driver {driver.user.username} to request #{waste_request.id}{grouped_note}'
        )

        # Notify the other reporters that their report is being handled too.
        for sibling in siblings:
            if sibling.user_id:
                _create_notification(
                    user=sibling.user,
                    title='Driver Assigned',
                    message=f'Driver {driver.user.username} has been assigned to your request.',
                    notification_type='info',
                    related_request=sibling,
                )

        # Notify user (guest/anonymous requests won't have a user to notify)
        if waste_request.user_id:
            _create_notification(
                user=waste_request.user,
                title='Driver Assigned',
                message=f'Driver {driver.user.username} has been assigned to your request.',
                notification_type='info',
                related_request=waste_request,
            )

        # Also notify the driver themselves — this is what makes the
        # toast/badge show up on their dashboard when admin hands them a
        # new pickup directly (as opposed to via generate_optimal below).
        # This is the ESSENTIAL notification for the driver on this action.
        _notify_driver(
            driver,
            title='New Pickup Assigned',
            message=f'You have been assigned pickup request #{waste_request.id}'
                    f'{" at " + waste_request.pickup_address if waste_request.pickup_address else ""}.',
            notification_type='info',
            related_request=waste_request,
        )

        return Response(WasteRequestSerializer(waste_request, context={'request': request}).data)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def claim_guest_requests(self, request):
        tokens = request.data.get('guest_tokens', [])
        if not tokens or not isinstance(tokens, list):
            return Response({'error': 'guest_tokens (list) is required.'}, status=status.HTTP_400_BAD_REQUEST)

        qs = WasteRequest.objects.filter(guest_token__in=tokens, user__isnull=True)
        claimed_requests = list(qs)  # update() अघि instance haru चाहिन्छ (id र notification को लागि)
        claimed_ids = [wr.id for wr in claimed_requests]
        claimed_count = qs.update(user=request.user)

        if claimed_ids:
            _log_admin_action(
                request, 'update', 'WasteRequest', None,
                f'{request.user.username} claimed {claimed_count} guest request(s): {claimed_ids}'
            )

            # ── User लाई notify गर्ने — यही हिस्सा हराएको थियो ──────────────
            for wr in claimed_requests:
                _create_notification(
                    user=request.user,
                    title='Request Linked to Your Account',
                    message=f'Your previously submitted report #{wr.id} is now linked to your account.',
                    notification_type='success',
                    related_request=wr,
                )

        return Response({
            'claimed': claimed_count,
            'claimed_ids': claimed_ids,
        })
    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_status(self, request, pk=None):
        """
        PATCH /api/waste-requests/{id}/update_status/ — driver/admin updates request status.
        Apawad (exception): request ko malik (owner) le aफnै 'pending' request lai
        'cancelled' ma matra move garna paaucha — home.html/user_requests.html ko
        "Cancel" button le yehi endpoint use garcha, tesैle purano role-check le
        normal 'user' lai 403 dinthyo.

        GPS ENFORCEMENT (new): new_status == 'completed' huda driver/admin le
        latitude/longitude pathaunai parcha — natra hard-block, DB ma kehi
        pani save hunna. Yo GPS lai pickup location sanga compare gareर
        completion_flagged set garincha, jasले admin lai suspicious
        (location mismatch) completion haru chinnu dincha.
        """
        waste_request = self.get_object()
        user = request.user
        new_status = request.data.get('status')

        is_owner_self_cancel = (
            user.role == 'user'
            and waste_request.user_id == user.id
            and waste_request.status == 'pending'
            and new_status == 'cancelled'
        )

        if user.role not in ('admin', 'driver') and not is_owner_self_cancel:
            return Response({'error': 'Drivers and admins only.'}, status=status.HTTP_403_FORBIDDEN)
        valid_statuses = [s[0] for s in WasteRequest.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response({'error': f'Invalid status. Choose: {valid_statuses}'}, status=status.HTTP_400_BAD_REQUEST)

        # ── HARD BLOCK: GPS चाहिन्छ, नत्र "Completed" mark गर्न मिल्दैन ──────
        # This applies to DRIVERS, who are meant to be standing at the pickup
        # when they close a job — their GPS is the proof of that. Admins are
        # doing back-office corrections from a desk (closing stale jobs,
        # fixing a driver's mistake) and have no meaningful location to send,
        # so requiring it from them would just block legitimate admin work.
        comp_lat = comp_lng = None
        if new_status == 'completed':
            raw_lat = request.data.get('latitude')
            raw_lng = request.data.get('longitude')
            missing_gps = raw_lat in (None, '') or raw_lng in (None, '')
            if missing_gps and user.role != 'admin':
                return Response(
                    {'error': 'GPS location is required to mark this request as completed. Please enable location access and try again.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not missing_gps:
                try:
                    comp_lat = float(raw_lat)
                    comp_lng = float(raw_lng)
                except (TypeError, ValueError):
                    return Response({'error': 'Invalid GPS coordinates.'}, status=status.HTTP_400_BAD_REQUEST)

        old_status = waste_request.status

        waste_request.status = new_status
        update_fields = ['status']
        if new_status == 'completed':
            waste_request.completed_at = timezone.now()
            update_fields.append('completed_at')

            # Driver ले पठाएको वास्तविक GPS save गर्ने
            waste_request.completion_latitude = comp_lat
            waste_request.completion_longitude = comp_lng
            update_fields += ['completion_latitude', 'completion_longitude']

            # Pickup location (लगभग जहाँ फोहोर रिपोर्ट भएको थियो) सँग तुलना गर्ने —
            # latitude/longitude नभए photo_latitude/longitude fallback गर्ने
            pickup_lat = waste_request.latitude if waste_request.latitude is not None else waste_request.photo_latitude
            pickup_lng = waste_request.longitude if waste_request.longitude is not None else waste_request.photo_longitude

            if comp_lat is None or comp_lng is None:
                # Admin desk-closure: no location to compare against, so there
                # is nothing to flag.
                waste_request.completion_distance_meters = None
                waste_request.completion_flagged = False
                update_fields += ['completion_distance_meters', 'completion_flagged']
            elif pickup_lat is not None and pickup_lng is not None:
                dist = _haversine_meters(float(pickup_lat), float(pickup_lng), comp_lat, comp_lng)
                waste_request.completion_distance_meters = round(dist, 1)
                waste_request.completion_flagged = dist > COMPLETION_DISTANCE_THRESHOLD_METERS
                update_fields += ['completion_distance_meters', 'completion_flagged']

                if waste_request.completion_flagged:
                    _log_admin_action(
                        request, 'other', 'WasteRequest', waste_request,
                        f'⚠️ Request #{waste_request.id} marked completed {round(dist)}m away from the '
                        f'reported pickup location by driver {user.username} — flagged for admin review.'
                    )
            else:
                # Pickup को आफ्नै GPS छैन भने compare गर्न सकिँदैन — flag नगर्ने
                waste_request.completion_distance_meters = None
                waste_request.completion_flagged = False
                update_fields += ['completion_distance_meters', 'completion_flagged']

        # Owner le aफnै request cancel garyo bhane, seedhai Recycle Bin ma pani
        # sarne — home/"My Requests" bata haraera Recycle Bin ma dekhincha,
        # jahaँ bata pachi restore ya permanently delete garna milcha.
        if is_owner_self_cancel:
            waste_request.is_deleted = True
            waste_request.deleted_at = timezone.now()
            update_fields += ['is_deleted', 'deleted_at']

        waste_request.save(update_fields=update_fields)

        # Bump the driver's lifetime trip counter the FIRST time a request
        # becomes 'completed' (guarded by old_status != 'completed' so
        # re-saving/re-triggering an already-completed request doesn't
        # double-count it). This is what "Total Trips" on the driver
        # dashboard reads from — without this it always stays at 0.
        if new_status == 'completed' and old_status != 'completed' and waste_request.driver_id:
            Driver.objects.filter(pk=waste_request.driver_id).update(
                total_trips=F('total_trips') + 1
            )

        # ── Close out the rest of the cluster ────────────────────────────────
        # The driver cleared one physical spot, so every other open report of
        # that same spot is done too. Doing this here means the other reporters
        # get told, instead of being left with a report that stays "pending"
        # forever against waste that no longer exists.
        completed_siblings = []
        if new_status == 'completed' and old_status != 'completed':
            for sibling in _same_location_siblings(waste_request):
                sibling.status = 'completed'
                sibling.completed_at = waste_request.completed_at
                sibling.completion_latitude = comp_lat
                sibling.completion_longitude = comp_lng
                sibling.completion_distance_meters = None
                sibling.completion_flagged = False
                sibling.save(update_fields=[
                    'status', 'completed_at', 'completion_latitude',
                    'completion_longitude', 'completion_distance_meters',
                    'completion_flagged',
                ])
                completed_siblings.append(sibling)

            if completed_siblings:
                _log_admin_action(
                    request, 'status_change', 'WasteRequest', waste_request,
                    f'Request #{waste_request.id} completion also closed '
                    f'{len(completed_siblings)} same-location request(s): '
                    f'{[s.id for s in completed_siblings]}'
                )

        # Log all status changes, including self-cancels, so users' own
        # actions on their requests appear in the audit trail too.
        _log_admin_action(
            request, 'status_change', 'WasteRequest', waste_request,
            f'Request #{waste_request.id} status changed to {new_status} by {user.username}'
        )

        # Guest/anonymous requests won't have a user to notify.
        # On completion every reporter in the cluster hears about it — each
        # against their OWN request, so the notification links somewhere
        # meaningful for them rather than to a stranger's report.
        if new_status == 'completed':
            for closed in [waste_request] + completed_siblings:
                if closed.user_id:
                    _create_notification(
                        user=closed.user,
                        title='Report Completed',
                        message=f'Your report #{closed.id} has been completed. Thank you!',
                        notification_type='success',
                        related_request=closed,
                    )
        elif waste_request.user_id:
            _create_notification(
                user=waste_request.user,
                title='Request Status Updated',
                message=f'Your request status changed to: {new_status}.',
                notification_type='info',
                related_request=waste_request,
            )

        # If an admin (not the driver themselves) changes the status
        # on a request that has an assigned driver, let that driver know
        # too — e.g. admin marks something cancelled/reassigned on their
        # behalf while they're out on the road. Essential for the driver
        # so they don't keep working a job that's been pulled/changed.
        if user.role == 'admin' and waste_request.driver_id:
            _notify_driver(
                waste_request.driver,
                title='Request Status Changed',
                message=f'Request #{waste_request.id} was updated to "{new_status}" by an admin.',
                notification_type='info',
                related_request=waste_request,
            )

        return Response(WasteRequestSerializer(waste_request, context={'request': request}).data)

    @action(detail=True, methods=['patch'])
    def soft_delete(self, request, pk=None):
        """
        PATCH /api/waste-requests/{id}/soft_delete/
        Hard-delete nagari request lai Recycle Bin ma sarne.
        get_object() le already IsOwnerOrAdmin check garisakeko huncha, so
        yaha thap role-check chaहिदैन.
        """
        waste_request = self.get_object()
        waste_request.is_deleted = True
        waste_request.deleted_at = timezone.now()
        waste_request.save(update_fields=['is_deleted', 'deleted_at'])
        return Response(WasteRequestSerializer(waste_request, context={'request': request}).data)

    @action(detail=True, methods=['patch'])
    def restore(self, request, pk=None):
        """
        PATCH /api/waste-requests/{id}/restore/
        Recycle Bin bata request lai pheri saकिय (active) list ma फर्काउने.
        Cancel garera bin ma aayeko request bhaye, restore garda status pani
        'pending' ma farkincha — natra 'cancelled' nai rahera home/"My Requests"
        ma active jasto dekhinthyo tara kaम nagarne huन्थ्यो.
        """
        waste_request = self.get_object()
        update_fields = ['is_deleted', 'deleted_at']
        waste_request.is_deleted = False
        waste_request.deleted_at = None
        if waste_request.status == 'cancelled':
            waste_request.status = 'pending'
            update_fields.append('status')
        waste_request.save(update_fields=update_fields)
        return Response(WasteRequestSerializer(waste_request, context={'request': request}).data)

    @action(detail=False, methods=['get'])
    def recycle_bin(self, request):
        """
        GET /api/waste-requests/recycle_bin/
        Logged-in user (ya admin/driver) ko soft-deleted request haru list
        garne — sidebar ko Recycle Bin badge (base.html) le yehi endpoint
        fetch garcha count populate garna. Ownership scoping get_queryset()
        sanga same rakheko (user/driver/admin), tara yaha 'list' action
        haina, tesैle is_deleted=True lai explicitly filter garnu pareko.
        """
        base_qs = WasteRequest.objects.select_related(
            'user', 'driver', 'driver__user', 'driver__vehicle',
        ).prefetch_related('extra_photos')
        user = request.user
        if user.role == 'admin':
            qs = base_qs
        elif user.role == 'driver':
            qs = base_qs.filter(driver__user=user)
        else:
            qs = base_qs.filter(user=user)

        qs = qs.filter(is_deleted=True).order_by('-deleted_at')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class RouteViewSet(viewsets.ModelViewSet):
    """Route planning and management. Admin only for write."""
    queryset = Route.objects.select_related('driver__user', 'vehicle').prefetch_related(
        'waste_requests', 'bins'
    ).all()
    serializer_class = RouteSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['status', 'driver__user__username']
    ordering_fields = ['planned_date', 'created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role == 'driver':
            qs = qs.filter(driver__user=self.request.user)
        return qs

    def perform_create(self, serializer):
        route = serializer.save()
        _log_admin_action(self.request, 'create', 'Route', route, f'Created route #{route.id}')

    @action(detail=True, methods=['patch'])
    def start_route(self, request, pk=None):
        """PATCH /api/routes/{id}/start_route/ — mark route as active."""
        route = self.get_object()
        route.status = 'active'
        route.started_at = timezone.now()
        route.save(update_fields=['status', 'started_at'])

        _log_admin_action(request, 'status_change', 'Route', route, f'Route #{route.id} started')
        return Response(RouteSerializer(route).data)

    @action(detail=True, methods=['patch'])
    def complete_route(self, request, pk=None):
        """PATCH /api/routes/{id}/complete_route/ — mark route as completed."""
        route = self.get_object()
        route.status = 'completed'
        route.completed_at = timezone.now()
        route.save(update_fields=['status', 'completed_at'])

        _log_admin_action(request, 'status_change', 'Route', route, f'Route #{route.id} completed')
        return Response(RouteSerializer(route).data)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def generate_optimal(self, request):
        """
        POST /api/routes/generate_optimal/ — generate optimized route for driver.
        Request body: {
            "driver_id": int,
            "waste_request_ids": [int, ...],   # optional if include_all_pending=True
            "bin_ids": [int, ...],
            "planned_date": "YYYY-MM-DD",
            "include_all_pending": bool        # auto-select every unassigned pending request
        }
        """
        from django.db.utils import IntegrityError
        from .route_optimizer import generate_optimal_route

        driver_id = request.data.get('driver_id')
        input_request_ids = request.data.get('waste_request_ids', [])
        bin_ids = request.data.get('bin_ids', [])
        planned_date = request.data.get('planned_date')
        include_all_pending = request.data.get('include_all_pending', False)

        if not driver_id:
            return Response({'error': 'driver_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            driver = Driver.objects.get(id=driver_id)
        except Driver.DoesNotExist:
            return Response({'error': 'Driver not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check permissions
        if request.user.role != 'admin' and driver.user != request.user:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        # Parse planned_date once, outside the transaction — pure parsing, no DB touch.
        if planned_date:
            try:
                planned_date = datetime.strptime(planned_date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return Response(
                    {'error': 'planned_date must be in YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            planned_date = datetime.now().date()

        # ── Transaction + row locking ───────────────────────────────────────
        # Two concurrent admins can't double-assign the same request because:
        #   1. WasteRequest rows are SELECT … FOR UPDATE SKIP LOCKED inside
        #      the atomic() block. The first admin to reach this point locks
        #      the rows; the other admin's query SKIPS them (so they are
        #      silently excluded from the race, no deadlock, no double-assign).
        #   2. The Route table has a UniqueConstraint(driver, planned_date,
        #      status='planned'). Even if two TXNs both pass the get() check
        #      in the milliseconds before .create(), the second insert raises
        #      IntegrityError → we catch, retry once, and load the row the
        #      first TXN created.
        #   3. Everything that mutates state (route create/update, M2M set,
        #      bulk request update, per-user notifications) lives inside a
        #      single transaction.atomic() block, so crash mid-way = full
        #      rollback = no partial state.
        MAX_CREATE_RETRIES = 2
        route = None
        created = False
        route_data = None
        locked_requests = []
        for attempt in range(1, MAX_CREATE_RETRIES + 1):
            try:
                with transaction.atomic():
                    # Step 1 — if include_all_pending, RE-QUERY the pending
                    # IDs inside the transaction with row locks. The IDs read
                    # earlier (before the TXN) were a stale snapshot and any
                    # one of them could have been assigned by another admin
                    # since we read them.
                    if include_all_pending:
                        locked_ids = list(
                            WasteRequest.objects.filter(
                                status='pending',
                                driver__isnull=True,
                                is_deleted=False,
                            ).filter(
                                Q(latitude__isnull=False, longitude__isnull=False) |
                                Q(photo_latitude__isnull=False, photo_longitude__isnull=False)
                            ).select_for_update(skip_locked=True)
                             .values_list('id', flat=True)
                        )
                        if not locked_ids:
                            return Response(
                                {'error': 'No pending requests with location data found (all were already assigned by another user).'},
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                        input_request_ids = locked_ids

                    # Step 2 — lock only the requests that are still
                    # assignable (pending + no driver + not deleted). Any
                    # rows already locked by another concurrent admin are
                    # SKIP LOCKED'd out of the final set — no deadlock.
                    locked_requests = list(
                        WasteRequest.objects.filter(
                            id__in=input_request_ids,
                            status='pending',
                            driver__isnull=True,
                            is_deleted=False,
                        ).select_for_update(skip_locked=True)
                        .select_related('user')
                    )
                    waste_request_ids = [wr.id for wr in locked_requests]
                    if not waste_request_ids:
                        return Response(
                            {'error': 'All selected requests were already assigned, deleted, or are locked by another user.'},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    # Step 3 — generate optimal geometry on the actually-
                    # locked subset (not the original input_ids list, which
                    # might have contained already-locked rows skipped above).
                    route_data = generate_optimal_route(driver, waste_request_ids, bin_ids)
                    if 'error' in route_data:
                        return Response(route_data, status=status.HTTP_400_BAD_REQUEST)

                    # Step 4 — create-or-update the route. Because of the
                    # UniqueConstraint(driver, planned_date, status='planned')
                    # on the Route model, two concurrent admins can't both
                    # insert a duplicate planned route; IntegrityError triggers
                    # the retry loop (outer try/except).
                    try:
                        route = Route.objects.select_for_update().get(
                            driver=driver,
                            planned_date=planned_date,
                            status='planned',
                        )
                        created = False
                        route.vehicle = driver.vehicle
                        route.total_distance_km = route_data['total_distance_km']
                        route.save(update_fields=['vehicle', 'total_distance_km'])
                    except Route.DoesNotExist:
                        route = Route.objects.create(
                            driver=driver,
                            planned_date=planned_date,
                            status='planned',
                            vehicle=driver.vehicle,
                            total_distance_km=route_data['total_distance_km'],
                        )
                        created = True

                    # Step 5 — M2M assignments (must be inside TXN because
                    # the join table rows must commit alongside the request
                    # status update below)
                    route.waste_requests.set(waste_request_ids)
                    if bin_ids:
                        route.bins.set(bin_ids)

                    # Step 6 — bulk-update driver assignment on the locked
                    # request rows. Rows are already row-locked from step 2,
                    # so this .update() cannot be interleaved with another
                    # admin's UPDATE on the same IDs.
                    WasteRequest.objects.filter(id__in=waste_request_ids).update(
                        driver=driver, status='assigned',
                    )

                    # Step 7 — per-user notifications (writes to DB via
                    # _create_notification, kept inside the TXN so they
                    # roll back if anything later throws). locked_requests
                    # already .select_related('user') so this loop is N+1-free.
                    for wr in locked_requests:
                        if wr.user_id:
                            _create_notification(
                                user=wr.user,
                                title='Driver Assigned',
                                message=f'Driver {driver.user.username} has been assigned to your request and is on route #{route.id}.',
                                notification_type='info',
                                related_request=wr,
                            )

                # End of atomic() block — TXN committed here, rows unlocked
                break

            except IntegrityError:
                # UniqueConstraint collision on Route(driver, planned_date,
                # status='planned'). Another concurrent admin just created
                # the exact route row we wanted. Retry the TXN once so we
                # load that row via .get() instead of trying to insert again.
                if attempt >= MAX_CREATE_RETRIES:
                    return Response(
                        {'error': 'A route for this driver and date was just created by another user. Please reload and try again.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                continue

        # ── Post-commit side effects (must NOT be inside atomic()) ──────────
        # These actions call channels WS senders (network) and/or must not
        # be rolled back once the TXN has committed. If we put them inside
        # atomic(), the DB rollback would still leave stale WS messages in
        # flight to the browser.

        # Notify the driver once about the whole route (not per-request).
        _notify_driver(
            driver,
            title='New Route Generated',
            message=f'A new route (#{route.id}) with {route_data["total_stops"]} stop(s) '
                    f'and {route_data["total_distance_km"]} km has been planned for {planned_date}.',
            notification_type='info',
        )

        _log_admin_action(
            request, 'create' if created else 'update', 'Route', route,
            f'Generated optimal route for driver {driver.user.username} ({route_data["total_stops"]} stops)'
        )

        # Broadcast route geometry via WebSocket to driver-facing map pages.
        if CHANNEL_LAYER is not None:
            async_to_sync(CHANNEL_LAYER.group_send)(
                'driver_locations',
                {
                    'type': 'route_update',
                    'driver_id': driver.id,
                    'route_id': route.id,
                    'waypoints': route_data['waypoints'],
                    'total_distance': route_data['total_distance_km'],
                    'total_stops': route_data['total_stops'],
                }
            )

        return Response({
            'route': RouteSerializer(route).data,
            'route_data': route_data,
        }, status=status.HTTP_201_CREATED)


class ScheduleViewSet(viewsets.ModelViewSet):
    """Recurring collection schedules. Admin manages, all read."""
    queryset = Schedule.objects.select_related('driver__user', 'vehicle').all()
    serializer_class = ScheduleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['zone_name', 'frequency', 'driver__user__username']

    def perform_create(self, serializer):
        schedule = serializer.save()
        _log_admin_action(self.request, 'create', 'Schedule', schedule, f'Created schedule for {schedule.zone_name}')

        # Let the assigned driver know they've got a new recurring
        # zone schedule — essential info for planning their week.
        if schedule.driver_id:
            _notify_driver(
                schedule.driver,
                title='New Zone Schedule Assigned',
                message=f'You have been assigned to the "{schedule.zone_name}" collection '
                        f'schedule ({schedule.get_frequency_display()}).',
                notification_type='info',
            )

    def perform_update(self, serializer):
        schedule = serializer.save()
        _log_admin_action(self.request, 'update', 'Schedule', schedule, f'Updated schedule for {schedule.zone_name}')

        # Same as above, for edits (e.g. day/frequency changed, or a
        # driver newly assigned via the edit flow rather than at creation).
        if schedule.driver_id:
            _notify_driver(
                schedule.driver,
                title='Zone Schedule Updated',
                message=f'Your collection schedule for "{schedule.zone_name}" has been updated.',
                notification_type='info',
            )

    def perform_destroy(self, instance):
        _log_admin_action(self.request, 'delete', 'Schedule', instance, f'Removed schedule for {instance.zone_name}')
        instance.delete()


class NotificationViewSet(viewsets.ModelViewSet):
    """
    User notifications.
    Users see only their own. Admins see all.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        qs = Notification.objects.select_related(
            'user',
            'related_request',
            'related_request__user',
            'related_request__driver',
            'related_request__driver__user',
            'related_request__driver__vehicle',
        )
        # Admin ko lagi pani afnै account ko notification matra —
        # 'return qs' le sabai user ko personal notification samet
        # admin ko feed ma dekhauँdaithyo (privacy leak + confusing UI).
        # Checkpoint added/updated/removed jasto admin-wide broadcast
        # _notify_all_users() le admin lai afnै copy pahilehi diisakeko
        # huncha, tesैle yo filter le tiनীहरूलाई hataउँdaina.
        return qs.filter(user=user)

    @action(detail=False, methods=['patch'])
    def mark_all_read(self, request):
        qs = Notification.objects.filter(is_read=False)
        if request.user.role != 'admin':
            qs = qs.filter(user=request.user)
        qs.update(is_read=True)
        return Response({'message': 'All notifications marked as read.'})

    @action(detail=False, methods=['get'])
    def unread(self, request):
        qs = self.get_queryset().filter(is_read=False)
        # get_queryset() le admin ko lagi sabai notifications return garcha — correct chha
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class AdminLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Admin activity logs - read-only for admins only.
    Tracks all admin actions for audit trail.
    """
    queryset = AdminLog.objects.select_related('admin_user').order_by('-created_at')
    serializer_class = AdminLogSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['action', 'content_type', 'admin_user__username']
    ordering_fields = ['created_at', 'action']


class SystemSettingsViewSet(viewsets.ModelViewSet):
    """
    System-wide settings management.
    Create, read, update, delete settings. Admin-only.
    """
    queryset = SystemSettings.objects.all()
    serializer_class = SystemSettingsSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    lookup_field = 'key'

    def perform_create(self, serializer):
        settings_obj = serializer.save(updated_by=self.request.user)
        _log_admin_action(self.request, 'create', 'SystemSettings', settings_obj, f'Created setting {settings_obj.key}')

    def perform_update(self, serializer):
        settings_obj = serializer.save(updated_by=self.request.user)
        _log_admin_action(self.request, 'update', 'SystemSettings', settings_obj, f'Updated setting {settings_obj.key}')

    def perform_destroy(self, instance):
        _log_admin_action(self.request, 'delete', 'SystemSettings', instance, f'Deleted setting {instance.key}')
        instance.delete()


class ComplaintViewSet(viewsets.ModelViewSet):
    """
    User complaints.
    - Regular users: create + view/edit their own complaints only.
    - Admins: full access, plus the update_status action to move a
      complaint through pending -> under_review -> completed.
    """
    serializer_class = ComplaintSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['subject', 'description', 'status', 'user__username']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action == 'update_status':
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated(), IsOwnerOrAdmin()]

    def get_queryset(self):
        user = self.request.user
        qs = Complaint.objects.select_related('user')

        if user.role != 'admin':
            qs = qs.filter(user=user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        complaint = serializer.save(user=self.request.user)
        _log_admin_action(
            self.request, 'create', 'Complaint', complaint,
            f'{self.request.user.username} filed complaint #{complaint.id} ({complaint.get_complaint_type_display()})'
        )
        # NAYA: admin lai live notify garne — yehi bina admin ko complaints
        # badge kahilyai reload nagari update hudaina thiyo
        _notify_admins(
            title='New Complaint Filed',
            message=f'{self.request.user.username} filed a complaint: "{complaint.subject}".',
            notification_type='warning',
        )

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsAdminUser])
    def update_status(self, request, pk=None):
        """PATCH /api/complaints/{id}/update_status/ — admin updates complaint status."""
        complaint = self.get_object()
        new_status = request.data.get('status')
        valid_statuses = [s[0] for s in Complaint.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response({'error': f'Invalid status. Choose: {valid_statuses}'}, status=status.HTTP_400_BAD_REQUEST)

        complaint.status = new_status
        update_fields = ['status']
        if 'admin_response' in request.data:
            complaint.admin_response = request.data['admin_response']
            update_fields.append('admin_response')
        complaint.save(update_fields=update_fields)

        _log_admin_action(
            request, 'status_change', 'Complaint', complaint,
            f'Complaint #{complaint.id} status changed to {new_status}'
        )

        _create_notification(
            user=complaint.user,
            title='Complaint Status Updated',
            message=f'Your complaint "{complaint.subject}" status changed to: {complaint.get_status_display()}.',
            notification_type='success' if new_status == 'completed' else 'info',
        )
        return Response(ComplaintSerializer(complaint, context={'request': request}).data)