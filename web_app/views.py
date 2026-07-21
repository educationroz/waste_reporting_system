from django.contrib.auth import get_user_model, logout as django_logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import ListView, TemplateView

from api_app.models import Driver, Notification, Route, Schedule, Vehicle, WasteRequest, Complaint

User = get_user_model()


# ─── Public / Auth Pages ───────────────────────────────────────────────────────

class HomeView(TemplateView):
    template_name = 'web_app/home.html'

    def dispatch(self, request, *args, **kwargs):
        # Admin/driver lai afnै dashboard ma pathaune, tara guest ra normal 'user' lai home nai dekhaune
        if request.user.is_authenticated and request.user.role in ('admin', 'driver'):
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # ── Map: sabai lai dekhine (login chahidaina) ──────────────────
        qs = WasteRequest.objects.filter(
            status__in=['pending', 'assigned', 'in_progress', 'completed'],
            latitude__isnull=False,
            longitude__isnull=False
        ).select_related('user', 'driver__user').order_by('-created_at')[:100]

        public_data = []
        for req in qs:
            public_data.append({
                'id': req.id,
                'latitude': float(req.latitude),
                'longitude': float(req.longitude),
                'status': req.status,
                'status_display': req.get_status_display(),
                'waste_type': req.waste_type,
                'waste_type_display': req.get_waste_type_display(),
                'pickup_address': req.pickup_address or '',
                'username': req.user.username if req.user else 'Unknown',
                'driver_name': req.driver.user.username if req.driver and req.driver.user else None,
            })
        ctx['public_requests'] = public_data

        if user.is_authenticated and user.role == 'user':
            ctx['my_requests'] = (
                WasteRequest.objects.filter(user=user, is_deleted=False)
                .select_related('driver__user')
                .order_by('-created_at')[:5]
            )
            ctx['pending_count'] = WasteRequest.objects.filter(user=user, status='pending', is_deleted=False).count()
            ctx['completed_count'] = WasteRequest.objects.filter(user=user, status='completed', is_deleted=False).count()
            ctx['unread_notifications'] = Notification.objects.filter(
                user=user, is_read=False
            ).order_by('-created_at')[:5]

        return ctx

class UserRequestListView(LoginRequiredMixin, ListView):
    template_name = 'web_app/user_requests.html'
    context_object_name = 'requests'
    paginate_by = 10

    def get_queryset(self):
        return (
            WasteRequest.objects.filter(user=self.request.user, is_deleted=False)
            .select_related('driver__user')
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['waste_type_choices'] = WasteRequest.WASTE_TYPE_CHOICES
        return ctx


class UserRecycleBinView(LoginRequiredMixin, ListView):
    """Naya requests haru jun user le 'delete' garyo (soft-delete), tiniharu
    yaha dekhincha jaba samma restore ya permanently delete nagariyeko huncha."""
    template_name = 'web_app/recycle_bin.html'
    context_object_name = 'deleted_requests'
    paginate_by = 20

    def get_queryset(self):
        return (
            WasteRequest.objects.filter(user=self.request.user, is_deleted=True)
            .select_related('driver__user')
            .order_by('-deleted_at')
        )


class UserComplaintListView(LoginRequiredMixin, ListView):
    # NOTE: this currently renders home.html — likely should be
    # 'web_app/user_complaints.html' unless that's intentional.
    template_name = 'web_app/home.html'
    context_object_name = 'complaints'
    paginate_by = 10

    def get_queryset(self):
        return (
            Complaint.objects.filter(user=self.request.user)
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['complaint_type_choices'] = Complaint.TYPE_CHOICES
        return ctx

class AdminComplaintListView(LoginRequiredMixin, ListView):
    template_name = 'web_app/admin_complaints.html'
    context_object_name = 'complaints'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = Complaint.objects.select_related('user').order_by('-created_at')

        status_filter = self.request.GET.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Complaint.STATUS_CHOICES
        ctx['current_status'] = self.request.GET.get('status', '')
        return ctx
    
class LoginPageView(TemplateView):
    """Renders the login page. Actual login handled via REST API + JS."""
    template_name = 'web_app/login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)


class RegisterPageView(TemplateView):
    """Renders the register page. Registration via REST API + JS."""
    template_name = 'web_app/register.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)



# ─── Admin Dashboard ───────────────────────────────────────────────────────────

class AdminDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'web_app/admin_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        
        # Try to get cached dashboard stats (5 minute TTL)
        cache_key = 'admin_dashboard_stats'
        cached_stats = cache.get(cache_key)
        
        if cached_stats:
            # Use cached data
            ctx.update(cached_stats)
        else:
            # Calculate statistics
            stats = {}
            stats['total_requests'] = WasteRequest.objects.count()
            stats['pending_requests'] = WasteRequest.objects.filter(status='pending').count()
            stats['assigned_requests_count'] = WasteRequest.objects.filter(status='assigned').count()
            stats['in_progress_requests_count'] = WasteRequest.objects.filter(status='in_progress').count()
            stats['completed_requests_count'] = WasteRequest.objects.filter(status='completed').count()
            stats['cancelled_requests_count'] = WasteRequest.objects.filter(status='cancelled').count()
            stats['overdue_requests'] = WasteRequest.objects.filter(
                status__in=['pending', 'assigned'],
                scheduled_date__lt=timezone.now()
            ).count()
            stats['active_drivers'] = Driver.objects.filter(is_available=True).count()
            stats['total_drivers'] = Driver.objects.count()
            stats['total_vehicles'] = Vehicle.objects.count()
            stats['available_vehicles'] = Vehicle.objects.filter(status='available').count()
            stats['vehicles_on_route'] = Vehicle.objects.filter(status='on_route').count()
            stats['total_users'] = User.objects.filter(role='user').count()
            stats['total_admin_users'] = User.objects.filter(role='admin').count()
            
            # Cache for 5 minutes (300 seconds)
            cache.set(cache_key, stats, 300)
            ctx.update(stats)
        
        # Non-cached data (always fresh - only 20 records max)
        ctx['recent_requests'] = (
            WasteRequest.objects.select_related('user', 'driver__user')
            .order_by('-created_at')[:10]
        )
        ctx['recent_status_changes'] = (
            WasteRequest.objects.select_related('user', 'driver__user')
            .order_by('-updated_at')[:7]
        )
        ctx['active_routes'] = Route.objects.filter(status='active').select_related(
            'driver__user', 'vehicle'
        )
        ctx['drivers'] = Driver.objects.select_related('user', 'vehicle').all()
        ctx['admin_role'] = self.request.user.role.title()
        ctx['now'] = timezone.now()
        
        # System alerts
        ctx['system_alerts'] = []
        if ctx['overdue_requests'] > 0:
            ctx['system_alerts'].append({
                'type': 'danger',
                'icon': 'exclamation-triangle',
                'title': f'{ctx["overdue_requests"]} Overdue Requests',
                'message': 'Requests past scheduled date need immediate attention',
            })
        if ctx['pending_requests'] > 5:
            ctx['system_alerts'].append({
                'type': 'warning',
                'icon': 'clock-history',
                'title': f'{ctx["pending_requests"]} Pending Requests',
                'message': 'Multiple requests awaiting driver assignment',
            })
        if ctx['active_drivers'] == 0:
            ctx['system_alerts'].append({
                'type': 'danger',
                'icon': 'exclamation-circle',
                'title': 'No Available Drivers',
                'message': 'All drivers are currently busy',
            })
        if ctx['available_vehicles'] == 0:
            ctx['system_alerts'].append({
                'type': 'warning',
                'icon': 'exclamation-circle',
                'title': 'No Available Vehicles',
                'message': 'All vehicles are currently in use or maintenance',
            })
        
        return ctx


from django.db.models import Q
from django.utils.dateparse import parse_date
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect


class AdminRequestListView(LoginRequiredMixin, ListView):
    model = WasteRequest
    context_object_name = 'requests'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return ['web_app/partials/admin_requests_table.html']
        return ['web_app/admin_requests.html']

    def get_queryset(self):
        qs = WasteRequest.objects.select_related('user', 'driver__user') \
                                   .prefetch_related('extra_photos') \
                                   .order_by('-created_at')

        status_filter = self.request.GET.get('status')
        waste_type_filter = self.request.GET.get('waste_type')
        search_query = self.request.GET.get('search', '').strip()
        report_date = parse_date(self.request.GET.get('report_date', '').strip())

        if status_filter:
            qs = qs.filter(status=status_filter)

        if waste_type_filter:
            qs = qs.filter(waste_type=waste_type_filter)

        if search_query:
            filters = Q(user__username__iexact=search_query) | \
                      Q(pickup_address__iexact=search_query) | \
                      Q(waste_type__iexact=search_query)

            if search_query.isdigit():
                filters |= Q(id=int(search_query))

            qs = qs.filter(filters)

        if report_date:
            qs = qs.filter(
                Q(created_at__date=report_date) |
                Q(scheduled_date__date=report_date)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['drivers'] = Driver.objects.filter(is_available=True).select_related('user')
        ctx['status_choices'] = WasteRequest.STATUS_CHOICES
        ctx['waste_type_choices'] = WasteRequest.WASTE_TYPE_CHOICES
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['current_search'] = self.request.GET.get('search', '')
        ctx['current_waste_type'] = self.request.GET.get('waste_type', '')
        ctx['current_report_date'] = self.request.GET.get('report_date', '')
        return ctx

class AdminDriverListView(LoginRequiredMixin, ListView):
    template_name = 'web_app/admin_drivers.html'
    context_object_name = 'drivers'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Driver.objects.select_related('user', 'vehicle').order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['vehicles'] = Vehicle.objects.filter(status='available')
        ctx['users_no_driver'] = User.objects.filter(
            role='driver', driver_profile__isnull=True
        )
        return ctx


class AdminVehicleListView(LoginRequiredMixin, ListView):
    template_name = 'web_app/admin_vehicles.html'
    context_object_name = 'vehicles'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Vehicle.objects.order_by('-created_at')

class AdminScheduleListView(LoginRequiredMixin, ListView):
    template_name = 'web_app/admin_schedules.html'
    context_object_name = 'schedules'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Schedule.objects.select_related('driver__user', 'vehicle').order_by('zone_name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['drivers'] = Driver.objects.filter(is_available=True).select_related('user')
        ctx['vehicles'] = Vehicle.objects.filter(status='available')
        return ctx



# ─── Driver Dashboard ──────────────────────────────────────────────────────────

class DriverDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'web_app/driver_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'driver':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        driver, _ = Driver.objects.get_or_create(
            user=user,
            defaults={
                'license_number': f'DRIVER-{user.id}',
                'is_available': True,
            },
        )
        ctx['driver'] = driver
        ctx['assigned_requests'] = (
            WasteRequest.objects.filter(driver=driver, status__in=['assigned', 'in_progress'])
            .select_related('user')
            .order_by('scheduled_date')
        )
        ctx['active_route'] = Route.objects.filter(
            driver=driver, status='active'
        ).first()

        now = timezone.now()

        # Filtered by `completed_at` — set once by update_status() the moment
        # a request's status first becomes 'completed'. This is accurate and
        # won't shift if the request is edited again later for other reasons.
        ctx['completed_today'] = WasteRequest.objects.filter(
            driver=driver,
            status='completed',
            completed_at__date=now.date(),
        ).count()

        # Trips completed in the current calendar month — used for salary calc.
        ctx['completed_this_month'] = WasteRequest.objects.filter(
            driver=driver,
            status='completed',
            completed_at__year=now.year,
            completed_at__month=now.month,
        ).count()
        ctx['current_month_label'] = now.strftime('%B %Y')

        ctx['today_schedule'] = Schedule.objects.filter(
            driver=driver, is_active=True
        )
        return ctx


class RoutePlanningView(LoginRequiredMixin, TemplateView):
    """Route planning and optimization for drivers and admins."""
    template_name = 'web_app/route_planning.html'

    def dispatch(self, request, *args, **kwargs):
        # Only drivers and admins can access
        if request.user.is_authenticated and request.user.role not in ['driver', 'admin']:
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        
        if user.role == 'driver':
            # Driver sees only their routes
            driver = Driver.objects.get(user=user)
            ctx['user_routes'] = Route.objects.filter(driver=driver).order_by('-planned_date')
        else:
            # Admin sees all routes
            ctx['user_routes'] = Route.objects.select_related('driver__user', 'vehicle').order_by('-planned_date')
        
        return ctx


# ─── Notifications Page ────────────────────────────────────────────────────────

class NotificationsView(LoginRequiredMixin, ListView):
    template_name = 'web_app/notifications.html'
    context_object_name = 'notifications'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return Notification.objects.order_by('-created_at')  # ← admins see all
        return Notification.objects.filter(
            user=user
        ).order_by('-created_at')


# ─── Admin Management Views ────────────────────────────────────────────────────

class AdminUsersManagementView(LoginRequiredMixin, ListView):
    """Manage admin users and their permissions."""
    template_name = 'web_app/admin_users.html'
    context_object_name = 'admin_users'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return User.objects.filter(role='admin').order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_admins'] = User.objects.filter(role='admin').count()
        ctx['active_admins'] = User.objects.filter(role='admin', is_active=True).count()
        ctx['inactive_admins'] = User.objects.filter(role='admin', is_active=False).count()
        ctx['all_users'] = User.objects.all().count()
        ctx['all_roles'] = dict(User.ROLE_CHOICES)
        return ctx


class AdminLogsView(LoginRequiredMixin, ListView):
    """View admin activity logs for audit trail."""
    template_name = 'web_app/admin_logs.html'
    context_object_name = 'logs'
    paginate_by = 50

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        from api_app.models import AdminLog
        qs = AdminLog.objects.select_related('admin_user').order_by('-created_at')
        
        # Filter by action if provided
        action_filter = self.request.GET.get('action')
        if action_filter:
            qs = qs.filter(action=action_filter)
        
        # Filter by operator username if provided
        operator_filter = self.request.GET.get('operator', '').strip()
        if operator_filter:
            qs = qs.filter(admin_user__username__icontains=operator_filter)
        
        return qs

    def get_context_data(self, **kwargs):
        from api_app.models import AdminLog
        ctx = super().get_context_data(**kwargs)
        ctx['action_choices'] = AdminLog.ACTION_CHOICES

        ctx['current_action'] = self.request.GET.get('action', '')
        ctx['current_operator'] = self.request.GET.get('operator', '')
        ctx['total_logs'] = AdminLog.objects.count()
        return ctx


class AdminSettingsView(LoginRequiredMixin, TemplateView):
    """Manage system settings and configuration."""
    template_name = 'web_app/admin_settings.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != 'admin':
            return redirect_by_role(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from api_app.models import SystemSettings
        ctx = super().get_context_data(**kwargs)
        ctx['settings'] = SystemSettings.objects.all()
        ctx['system_info'] = {
            'total_requests': WasteRequest.objects.count(),
            'total_users': User.objects.filter(role='user').count(),
            'total_drivers': Driver.objects.count(),
            'total_vehicles': Vehicle.objects.count(),
            'total_routes': Route.objects.count(),
            'database_status': 'Connected',
        }
        return ctx


# ─── Helper ────────────────────────────────────────────────────────────────────

def redirect_by_role(user):
    role_redirect = {
        'admin': '/admin-dashboard/',
        'driver': '/driver-dashboard/',
        'user': '/',
    }
    return redirect(role_redirect.get(user.role, '/'))


def web_logout(request):
    django_logout(request)
    return redirect('/login/')
