import io
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
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
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser # type: ignore
from rest_framework.views import APIView
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

User = get_user_model()

try:
    CHANNEL_LAYER = get_channel_layer()
except InvalidChannelLayerError:
    CHANNEL_LAYER = None

import logging
logger = logging.getLogger('notif_debug')
logging.basicConfig(level=logging.INFO)

BACKUP_DIR = Path(settings.BASE_DIR) / 'backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


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


def _serialize_admin_user(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'full_name': user.get_full_name(),
        'is_active': user.is_active,
        'created_at': user.created_at.isoformat() if user.created_at else None,
    }


def _normalize_request_address(pickup_address):
    return ' '.join((pickup_address or '').split()).strip()


def _waste_request_location_filter(pickup_address=None, latitude=None, longitude=None):
    location_filter = Q()

    if latitude is not None and longitude is not None:
        lat = Decimal(str(latitude))
        lng = Decimal(str(longitude))
        # Roughly 11 meters at the equator. This keeps nearby reports at the
        # same physical location grouped together even if the map marker or
        # geocoder shifts slightly.
        tolerance = Decimal('0.0001')
        location_filter |= Q(
            latitude__gte=lat - tolerance,
            latitude__lte=lat + tolerance,
            longitude__gte=lng - tolerance,
            longitude__lte=lng + tolerance,
        )
    else:
        normalized_address = _normalize_request_address(pickup_address)
        if normalized_address:
            location_filter |= Q(pickup_address__iexact=normalized_address)

    return location_filter


def _related_waste_requests_for_location(pickup_address=None, latitude=None, longitude=None):
    location_filter = _waste_request_location_filter(
        pickup_address=pickup_address,
        latitude=latitude,
        longitude=longitude,
    )
    if not location_filter.children:
        return WasteRequest.objects.none()

    return (
        WasteRequest.objects.filter(is_deleted=False)
        .exclude(status='cancelled')
        .filter(location_filter)
        .select_related('user')
        .prefetch_related('submitting_users')
        .order_by('-created_at')
    )


class AdminUserCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        email = (request.data.get('email') or '').strip()
        password = request.data.get('password') or ''
        first_name = (request.data.get('first_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        is_active = request.data.get('is_active', True)

        if not username or not email or not password:
            return Response(
                {'success': False, 'message': 'Username, email, and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(username__iexact=username).exists():
            return Response(
                {'success': False, 'message': 'That username is already taken.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {'success': False, 'message': 'That email is already registered.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(password)
        except DjangoValidationError as exc:
            return Response(
                {'success': False, 'message': ' '.join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if isinstance(is_active, str):
            is_active = is_active.lower() in ('1', 'true', 'yes', 'on')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='admin',
            is_active=bool(is_active),
        )

        _log_admin_action(
            request,
            'create',
            'User',
            user,
            f'Created admin user {user.username}',
        )

        return Response(
            {
                'success': True,
                'message': 'Admin user created successfully.',
                'admin': _serialize_admin_user(user),
            },
            status=status.HTTP_201_CREATED,
        )


class AdminUserUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def patch(self, request, admin_id):
        try:
            user = User.objects.get(pk=admin_id, role='admin')
        except User.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Admin user not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        username = (request.data.get('username') or user.username).strip()
        email = (request.data.get('email') or user.email).strip()
        first_name = (request.data.get('first_name') or user.first_name).strip()
        last_name = (request.data.get('last_name') or user.last_name).strip()
        password = request.data.get('password') or ''
        is_active = request.data.get('is_active', user.is_active)

        if not username or not email:
            return Response(
                {'success': False, 'message': 'Username and email are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.exclude(pk=user.pk).filter(username__iexact=username).exists():
            return Response(
                {'success': False, 'message': 'That username is already taken.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.exclude(pk=user.pk).filter(email__iexact=email).exists():
            return Response(
                {'success': False, 'message': 'That email is already registered.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if isinstance(is_active, str):
            is_active = is_active.lower() in ('1', 'true', 'yes', 'on')

        changes = {}
        if user.username != username:
            changes['username'] = {'old': user.username, 'new': username}
            user.username = username
        if user.email != email:
            changes['email'] = {'old': user.email, 'new': email}
            user.email = email
        if user.first_name != first_name:
            changes['first_name'] = {'old': user.first_name, 'new': first_name}
            user.first_name = first_name
        if user.last_name != last_name:
            changes['last_name'] = {'old': user.last_name, 'new': last_name}
            user.last_name = last_name
        if user.is_active != bool(is_active):
            changes['is_active'] = {'old': user.is_active, 'new': bool(is_active)}
            user.is_active = bool(is_active)

        if password:
            try:
                validate_password(password, user=user)
            except DjangoValidationError as exc:
                return Response(
                    {'success': False, 'message': ' '.join(exc.messages)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user.set_password(password)
            changes['password'] = {'old': 'unchanged', 'new': 'updated'}

        user.role = 'admin'
        user.save()

        if changes:
            AdminLog.objects.create(
                admin_user=request.user,
                action='update',
                content_type='User',
                object_id=user.id,
                object_description=f'Updated admin user {user.username}',
                changes=changes,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

        return Response(
            {
                'success': True,
                'message': 'Admin user updated successfully.',
                'admin': _serialize_admin_user(user),
            },
            status=status.HTTP_200_OK,
        )


class AdminUserDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def delete(self, request, admin_id):
        try:
            user = User.objects.get(pk=admin_id, role='admin')
        except User.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Admin user not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.pk == request.user.pk:
            return Response(
                {'success': False, 'message': 'You cannot delete your own admin account from this screen.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(role='admin').count() <= 1:
            return Response(
                {'success': False, 'message': 'At least one admin account must remain active.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _log_admin_action(
            request,
            'delete',
            'User',
            user,
            f'Deleted admin user {user.username}',
        )
        user.delete()

        return Response(
            {'success': True, 'message': 'Admin user removed successfully.'},
            status=status.HTTP_200_OK,
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


def _get_backup_files():
    files = []
    for backup_path in sorted(BACKUP_DIR.glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True):
        # FIX: `from datetime import datetime` above binds `datetime` to the
        # *class*, not the module — so `datetime.timezone` doesn't exist on
        # it (that only lives on the datetime *module*). Using the
        # `dt_timezone` alias imported at the top avoids the collision with
        # `django.utils.timezone` (imported as `timezone`) while still
        # getting the real UTC tzinfo object.
        created_ts = datetime.fromtimestamp(backup_path.stat().st_mtime, tz=dt_timezone.utc)
        files.append({
            'file_name': backup_path.name,
            'size_bytes': backup_path.stat().st_size,
            'created_at': created_ts.isoformat(),
            'download_url': f'/api/database-backups/download/?file_name={backup_path.name}',
        })
    return files


def _resolve_backup_path(file_name):
    if not file_name:
        raise ValueError('file_name is required.')

    candidate = (BACKUP_DIR / file_name).resolve()
    backup_root = BACKUP_DIR.resolve()
    if candidate.parent != backup_root:
        raise ValueError('Invalid backup file location.')

    if not candidate.exists():
        raise FileNotFoundError(f'Backup file {file_name} was not found.')

    return candidate


class DatabaseBackupViewSet(viewsets.GenericViewSet):
    """Create, list, download, restore, and delete JSON database backups."""
    permission_classes = [IsAuthenticated, IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @action(detail=False, methods=['get'])
    def history(self, request):
        return Response(_get_backup_files())

    @action(detail=False, methods=['post'])
    def backup(self, request):
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        file_name = f'backup_{timestamp}.json'
        file_path = BACKUP_DIR / file_name

        buffer = io.StringIO()
        try:
            call_command(
                'dumpdata',
                stdout=buffer,
                indent=2,
                natural_foreign=True,
                natural_primary=True,
                verbosity=0,
            )
            file_path.write_text(buffer.getvalue(), encoding='utf-8')
        except Exception as exc:
            return Response({'error': f'Backup failed: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        _log_admin_action(request, 'other', 'DatabaseBackup', None, f'Created backup {file_name}')

        return Response({
            'file_name': file_name,
            'file_path': str(file_path),
            'size_bytes': file_path.stat().st_size,
            'created_at': timezone.now().isoformat(),
        })

    @action(detail=False, methods=['get'])
    def download(self, request):
        file_name = request.query_params.get('file_name')
        try:
            backup_path = _resolve_backup_path(file_name)
        except (ValueError, FileNotFoundError) as exc:
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
            backup_path = _resolve_backup_path(file_name)
        except (ValueError, FileNotFoundError) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        backup_path.unlink(missing_ok=True)
        _log_admin_action(request, 'delete', 'DatabaseBackup', None, f'Deleted backup {file_name}')
        return Response({'message': f'Backup {file_name} deleted successfully.'})

    @action(detail=False, methods=['post'])
    def restore(self, request):
        uploaded_file = request.FILES.get('backup_file')
        if not uploaded_file:
            return Response({'error': 'backup_file is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if not uploaded_file.name.endswith('.json'):
            return Response({'error': 'Only .json backup files are supported.'}, status=status.HTTP_400_BAD_REQUEST)

        backup_path = BACKUP_DIR / uploaded_file.name
        with backup_path.open('wb') as backup_file:
            for chunk in uploaded_file.chunks():
                backup_file.write(chunk)

        try:
            with transaction.atomic():
                call_command('flush', interactive=False, verbosity=0)
                call_command('loaddata', str(backup_path), verbosity=0)
        except Exception as exc:
            return Response({'error': f'Restore failed: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        _log_admin_action(request, 'other', 'DatabaseBackup', None, f'Restored from backup {uploaded_file.name}')

        return Response({
            'message': f'Backup {uploaded_file.name} restored successfully.',
            'restored_file': uploaded_file.name,
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

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        response_data = dict(serializer.data)
        headers = self.get_success_headers(serializer.data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

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

        related_requests = list(
            _related_waste_requests_for_location(
                pickup_address=waste_request.pickup_address,
                latitude=waste_request.latitude,
                longitude=waste_request.longitude,
            ).filter(status__in=['pending', 'assigned', 'in_progress'])
        )
        if waste_request not in related_requests:
            related_requests.append(waste_request)

        related_ids = [item.id for item in related_requests]
        WasteRequest.objects.filter(id__in=related_ids).update(driver=driver, status='assigned')
        waste_request.refresh_from_db()

        _log_admin_action(
            request, 'assign', 'WasteRequest', waste_request,
            f'Assigned driver {driver.user.username} to request #{waste_request.id}'
        )

        notified_user_ids = set()
        for related_request in related_requests:
            if related_request.user_id and related_request.user_id not in notified_user_ids:
                notified_user_ids.add(related_request.user_id)
                _create_notification(
                    user=related_request.user,
                    title='Driver Assigned',
                    message=(
                        f'Driver {driver.user.username} has been assigned to your '
                        f'waste report #{related_request.id}.'
                    ),
                    notification_type='info',
                    related_request=related_request,
                )
            for linked_user in related_request.submitting_users.all():
                if linked_user.id in notified_user_ids:
                    continue
                notified_user_ids.add(linked_user.id)
                _create_notification(
                    user=linked_user,
                    title='Driver Assigned',
                    message=(
                        f'Driver {driver.user.username} has been assigned to your '
                        f'waste report #{related_request.id}.'
                    ),
                    notification_type='info',
                    related_request=related_request,
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

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_status(self, request, pk=None):
        """
        PATCH /api/waste-requests/{id}/update_status/ — driver/admin updates request status.
        Apawad (exception): request ko malik (owner) le aफnै 'pending' request lai
        'cancelled' ma matra move garna paaucha — home.html/user_requests.html ko
        "Cancel" button le yehi endpoint use garcha, tesैle purano role-check le
        normal 'user' lai 403 dinthyo.
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

        old_status = waste_request.status

        waste_request.status = new_status
        update_fields = ['status']
        completion_timestamp = None
        if new_status == 'completed':
            completion_timestamp = timezone.now()
            waste_request.completed_at = completion_timestamp
            update_fields.append('completed_at')

        # Owner le aफnै request cancel garyo bhane, seedhai Recycle Bin ma pani
        # sarne — home/"My Requests" bata haraera Recycle Bin ma dekhincha,
        # jahaँ bata pachi restore ya permanently delete garna milcha.
        if is_owner_self_cancel:
            waste_request.is_deleted = True
            waste_request.deleted_at = timezone.now()
            update_fields += ['is_deleted', 'deleted_at']

        waste_request.save(update_fields=update_fields)

        if new_status == 'completed':
            related_requests = list(
                _related_waste_requests_for_location(
                    pickup_address=waste_request.pickup_address,
                    latitude=waste_request.latitude,
                    longitude=waste_request.longitude,
                )
            )
            if waste_request not in related_requests:
                related_requests.append(waste_request)

            related_ids = [
                item.id for item in related_requests
                if item.id != waste_request.id and item.status != 'completed'
            ]
            if related_ids and completion_timestamp is not None:
                WasteRequest.objects.filter(id__in=related_ids).update(
                    status='completed',
                    completed_at=completion_timestamp,
                )

            notified_user_ids = set()
            for related_request in related_requests:
                target_users = []
                if related_request.user_id:
                    target_users.append(related_request.user)
                target_users.extend(list(related_request.submitting_users.all()))

                for target_user in target_users:
                    if target_user.id in notified_user_ids:
                        continue
                    notified_user_ids.add(target_user.id)
                    _create_notification(
                        user=target_user,
                        title='Report Completed',
                        message=(
                            f'Your waste report #{related_request.id} has been completed and '
                            f'is now closed.'
                        ),
                        notification_type='success',
                        related_request=related_request,
                    )

        # Bump the driver's lifetime trip counter the FIRST time a request
        # becomes 'completed' (guarded by old_status != 'completed' so
        # re-saving/re-triggering an already-completed request doesn't
        # double-count it). This is what "Total Trips" on the driver
        # dashboard reads from — without this it always stays at 0.
        if new_status == 'completed' and old_status != 'completed' and waste_request.driver_id:
            Driver.objects.filter(pk=waste_request.driver_id).update(
                total_trips=F('total_trips') + 1
            )

        # Log all status changes, including self-cancels, so users' own
        # actions on their requests appear in the audit trail too.
        _log_admin_action(
            request, 'status_change', 'WasteRequest', waste_request,
            f'Request #{waste_request.id} status changed to {new_status} by {user.username}'
        )

        # Guest/anonymous requests won't have a user to notify
        if waste_request.user_id:
            _create_notification(
                user=waste_request.user,
                title='Request Status Updated',
                message=f'Your request status changed to: {new_status}.',
                notification_type='success' if new_status == 'completed' else 'info',
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
        from .route_optimizer import generate_optimal_route

        driver_id = request.data.get('driver_id')
        waste_request_ids = request.data.get('waste_request_ids', [])
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

        # Auto-select every unassigned pending request with valid coordinates,
        # so the generated route covers all reported pickups in one sweep.
        if include_all_pending:
            pending_qs = WasteRequest.objects.filter(
                status='pending',
                driver__isnull=True,
                is_deleted=False,
            ).filter(
                Q(latitude__isnull=False, longitude__isnull=False) |
                Q(photo_latitude__isnull=False, photo_longitude__isnull=False)
            )
            waste_request_ids = list(pending_qs.values_list('id', flat=True))
            if not waste_request_ids:
                return Response(
                    {'error': 'No pending requests with location data found.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Generate optimized route
        route_data = generate_optimal_route(driver, waste_request_ids, bin_ids)

        if 'error' in route_data:
            return Response(route_data, status=status.HTTP_400_BAD_REQUEST)

        # Create or update route
        if planned_date:
            planned_date = datetime.strptime(planned_date, '%Y-%m-%d').date()
        else:
            planned_date = datetime.now().date()

        route, created = Route.objects.get_or_create(
            driver=driver,
            planned_date=planned_date,
            status='planned',
            defaults={
                'vehicle': driver.vehicle,
                'total_distance_km': route_data['total_distance_km'],
            }
        )

        if not created:
            route.total_distance_km = route_data['total_distance_km']
            route.save(update_fields=['total_distance_km'])

        # Add waste requests and bins to route
        if waste_request_ids:
            route.waste_requests.set(waste_request_ids)
        if bin_ids:
            route.bins.set(bin_ids)

        # Auto-assign the driver to each request on the route, so pickup
        # status/driver reflects the plan and each user gets notified.
        if waste_request_ids:
            WasteRequest.objects.filter(id__in=waste_request_ids, status='pending').update(
                driver=driver, status='assigned'
            )
            for wr in WasteRequest.objects.filter(id__in=waste_request_ids):
                if wr.user_id:
                    _create_notification(
                        user=wr.user,
                        title='Driver Assigned',
                        message=f'Driver {driver.user.username} has been assigned to your request and is on route #{route.id}.',
                        notification_type='info',
                        related_request=wr,
                    )

        # Notify the driver once about the whole route (not per-request —
        # that would spam them with one toast per stop). This is the main
        # ESSENTIAL notification for a driver: a new route has been
        # planned for them and they should check the dashboard/map.
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

        # Broadcast route update via WebSocket
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
    Users see only their own — including admins. Broadcast notifications
    (e.g. new checkpoint) already create one row PER active user via
    _notify_all_users(), and admins are part of that loop too, so admin's
    own row is enough without also pulling everyone else's on top of it.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return Notification.objects.select_related(
            'user',
            'related_request',
            'related_request__user',
            'related_request__driver',
            'related_request__driver__user',
            'related_request__driver__vehicle',
        ).filter(user=self.request.user)

    @action(detail=False, methods=['patch'])
    def mark_all_read(self, request):
        qs = Notification.objects.filter(is_read=False, user=request.user)
        qs.update(is_read=True)
        return Response({'message': 'All notifications marked as read.'})

    @action(detail=False, methods=['get'])
    def unread(self, request):
        qs = self.get_queryset().filter(is_read=False)
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