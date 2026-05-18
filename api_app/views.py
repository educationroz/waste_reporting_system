from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .models import AdminLog, Bin, Driver, Notification, Route, Schedule, SystemSettings, Vehicle, WasteRequest
from .permissions import IsAdminOrReadOnly, IsAdminUser, IsOwnerOrAdmin
from .serializers import (
    AdminLogSerializer,
    BinSerializer,
    DriverSerializer,
    NotificationSerializer,
    RouteSerializer,
    ScheduleSerializer,
    SystemSettingsSerializer,
    VehicleSerializer,
    WasteRequestSerializer,
)

CHANNEL_LAYER = get_channel_layer()


class VehicleViewSet(viewsets.ModelViewSet):
    """CRUD for vehicles. Admins manage, all authenticated users read."""
    queryset = Vehicle.objects.prefetch_related('assigned_drivers__user', 'routes').order_by('-created_at')
    serializer_class = VehicleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['plate_number', 'vehicle_type', 'status']
    ordering_fields = ['created_at', 'status']

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

    @action(detail=False, methods=['get'])
    def available(self, request):
        """GET /api/drivers/available/ — available drivers only."""
        qs = Driver.objects.filter(is_available=True).select_related('user', 'vehicle')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class BinViewSet(viewsets.ModelViewSet):
    """CRUD for waste bins. Admins write, all authenticated users read."""
    queryset = Bin.objects.prefetch_related('routes').order_by('-created_at')
    serializer_class = BinSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['bin_code', 'waste_type', 'status', 'location_address']
    ordering_fields = ['created_at', 'status']

    @action(detail=False, methods=['get'])
    def full_bins(self, request):
        """GET /api/bins/full_bins/ — bins that are full or overflowing."""
        qs = Bin.objects.filter(status__in=['full', 'overflow']).prefetch_related('routes')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class WasteRequestViewSet(viewsets.ModelViewSet):
    """
    Waste pickup requests.
    - Regular users: create + view own requests only.
    - Drivers: view assigned requests; update status.
    - Admins: full access + assign drivers.
    """
    serializer_class = WasteRequestSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    parser_classes =[MultiPartParser, FormParser, JSONParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['status', 'waste_type', 'pickup_address', 'user__username']
    ordering_fields = ['created_at', 'scheduled_date', 'status']

    def get_queryset(self):
        user = self.request.user
        base_qs = WasteRequest.objects.select_related(
            'user',
            'driver',
            'driver__user',
            'driver__vehicle',
        )
        if user.role == 'admin':
            qs = base_qs
        elif user.role == 'driver':
            qs = base_qs.filter(driver__user=user)
        else:
            qs = base_qs.filter(user=user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by('-created_at')

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

        # Notify user
        Notification.objects.create(
            user=waste_request.user,
            title='Driver Assigned',
            message=f'Driver {driver.user.username} has been assigned to your request.',
            notification_type='info',
            related_request=waste_request,
        )
        return Response(WasteRequestSerializer(waste_request, context={'request': request}).data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_status(self, request, pk=None):
        """PATCH /api/waste-requests/{id}/update_status/ — driver/admin updates request status."""
        waste_request = self.get_object()
        user = request.user
        if user.role not in ('admin', 'driver'):
            return Response({'error': 'Drivers and admins only.'}, status=status.HTTP_403_FORBIDDEN)

        new_status = request.data.get('status')
        valid_statuses = [s[0] for s in WasteRequest.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response({'error': f'Invalid status. Choose: {valid_statuses}'}, status=status.HTTP_400_BAD_REQUEST)

        waste_request.status = new_status
        update_fields = ['status']
        if new_status == 'completed':
            waste_request.completed_at = timezone.now()
            update_fields.append('completed_at')
        waste_request.save(update_fields=update_fields)

        Notification.objects.create(
            user=waste_request.user,
            title='Request Status Updated',
            message=f'Your request status changed to: {new_status}.',
            notification_type='success' if new_status == 'completed' else 'info',
            related_request=waste_request,
        )
        return Response(WasteRequestSerializer(waste_request, context={'request': request}).data)


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

    @action(detail=True, methods=['patch'])
    def start_route(self, request, pk=None):
        """PATCH /api/routes/{id}/start_route/ — mark route as active."""
        route = self.get_object()
        route.status = 'active'
        route.started_at = timezone.now()
        route.save(update_fields=['status', 'started_at'])
        return Response(RouteSerializer(route).data)

    @action(detail=True, methods=['patch'])
    def complete_route(self, request, pk=None):
        """PATCH /api/routes/{id}/complete_route/ — mark route as completed."""
        route = self.get_object()
        route.status = 'completed'
        route.completed_at = timezone.now()
        route.save(update_fields=['status', 'completed_at'])
        return Response(RouteSerializer(route).data)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def generate_optimal(self, request):
        """
        POST /api/routes/generate_optimal/ — generate optimized route for driver.
        Request body: {
            "driver_id": int,
            "waste_request_ids": [int, ...],
            "bin_ids": [int, ...],
            "planned_date": "YYYY-MM-DD"
        }
        """
        from .route_optimizer import generate_optimal_route
        
        driver_id = request.data.get('driver_id')
        waste_request_ids = request.data.get('waste_request_ids', [])
        bin_ids = request.data.get('bin_ids', [])
        planned_date = request.data.get('planned_date')
        
        if not driver_id:
            return Response({'error': 'driver_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            driver = Driver.objects.get(id=driver_id)
        except Driver.DoesNotExist:
            return Response({'error': 'Driver not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check permissions
        if request.user.role != 'admin' and driver.user != request.user:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Generate optimized route
        route_data = generate_optimal_route(driver, waste_request_ids, bin_ids)
        
        if 'error' in route_data:
            return Response(route_data, status=status.HTTP_400_BAD_REQUEST)
        
        # Create or update route
        from datetime import datetime
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
        if user.role == 'admin':
            return qs
        return qs.filter(user=user)

    @action(detail=False, methods=['patch'])
    def mark_all_read(self, request):
        """PATCH /api/notifications/mark_all_read/ — mark all user notifications as read."""
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'message': 'All notifications marked as read.'})

    @action(detail=False, methods=['get'])
    def unread(self, request):
        """GET /api/notifications/unread/ — unread notifications only."""
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
        serializer.save(updated_by=self.request.user)
    
    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
