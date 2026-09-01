from django.urls import path

from .views import (
    AdminComplaintListView,
    AdminDashboardView,
    AdminDriverListView,
    AdminLogsView,
    AdminRequestListView,
    AdminScheduleListView,
    AdminSettingsView,
    AdminUsersManagementView,
    AdminVehicleListView,
    DriverDashboardView,
    ForgotPasswordPageView,
    HomeView,
    LoginPageView,
    NotificationsView,
    ProfilePageView,
    RegisterPageView,
    ResetPasswordPageView,
    RoutePlanningView,
    ServiceWorkerView,
    UserComplaintListView,
    UserRecycleBinView,
    UserRequestListView,
    web_logout,
)

urlpatterns = [
    # Service worker — must be served at root ('/sw.js', not
    # '/static/web_app/sw.js') so its default scope covers the whole app.
    path('sw.js', ServiceWorkerView.as_view(), name='service-worker'),
    # Public
    path('',          HomeView.as_view(),         name='home'),
    path('complaints/', UserComplaintListView.as_view(), name='user-complaints'),
    path('recycle-bin/', UserRecycleBinView.as_view(), name='user-recycle-bin'),
    path('login/',    LoginPageView.as_view(),    name='login'),
    path('logout/',   web_logout,                 name='web-logout'),
    path('profile/', ProfilePageView.as_view(), name='profile'),
    path('settings/', ProfilePageView.as_view(), name='personal-settings'),
    path('register/', RegisterPageView.as_view(), name='register'),
    # Password reset (pages only — the actual reset logic lives in
    # auth_app's /auth/password-reset/ and /auth/password-reset-confirm/
    # JSON endpoints, which these pages call via fetch())
    path('forgot-password/', ForgotPasswordPageView.as_view(), name='forgot-password'),
    path('reset-password/<str:uidb64>/<str:token>/', ResetPasswordPageView.as_view(), name='reset-password'),
    # User
    path('my-requests/',       UserRequestListView.as_view(), name='user-requests'),
    path('notifications/',     NotificationsView.as_view(),   name='notifications'),
    # Admin
    path('admin-dashboard/',   AdminDashboardView.as_view(),    name='admin-dashboard'),
    path('management/requests/',    AdminRequestListView.as_view(),  name='admin-requests'),
    path('management/complaints/',  AdminComplaintListView.as_view(), name='admin-complaints'),
    path('management/drivers/',     AdminDriverListView.as_view(),   name='admin-drivers'),
    path('management/vehicles/',    AdminVehicleListView.as_view(),  name='admin-vehicles'),
    path('management/schedules/',   AdminScheduleListView.as_view(), name='admin-schedules'),
    path('management/admin-users/', AdminUsersManagementView.as_view(), name='admin-users'),
    path('management/activity-logs/', AdminLogsView.as_view(), name='admin-logs'),
    path('management/settings/',    AdminSettingsView.as_view(), name='admin-settings'),
    # Driver
    path('driver-dashboard/',  DriverDashboardView.as_view(),  name='driver-dashboard'),
    # Route Planning
    path('route-planning/',    RoutePlanningView.as_view(),    name='route-planning'),
]