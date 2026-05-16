from django.urls import path

from .views import (
    AdminDashboardView,
    AdminDriverListView,
    AdminRequestListView,
    AdminScheduleListView,
    AdminVehicleListView,
    AdminUsersManagementView,
    AdminLogsView,
    AdminSettingsView,
    DriverDashboardView,
    HomeView,
    LoginPageView,
    NotificationsView,
    RegisterPageView,
    UserDashboardView,
    UserRequestListView,
    web_logout,
)

urlpatterns = [
    # Public
    path('',          HomeView.as_view(),         name='home'),
    path('login/',    LoginPageView.as_view(),    name='login'),
    path('logout/',   web_logout,                 name='web-logout'),
    path('register/', RegisterPageView.as_view(), name='register'),

    # User
    path('dashboard/',         UserDashboardView.as_view(),   name='user-dashboard'),
    path('my-requests/',       UserRequestListView.as_view(), name='user-requests'),
    path('notifications/',     NotificationsView.as_view(),   name='notifications'),

    # Admin
    path('admin-dashboard/',   AdminDashboardView.as_view(),    name='admin-dashboard'),
    path('management/requests/',    AdminRequestListView.as_view(),  name='admin-requests'),
    path('management/drivers/',     AdminDriverListView.as_view(),   name='admin-drivers'),
    path('management/vehicles/',    AdminVehicleListView.as_view(),  name='admin-vehicles'),
    path('management/schedules/',   AdminScheduleListView.as_view(), name='admin-schedules'),
    path('management/admin-users/', AdminUsersManagementView.as_view(), name='admin-users'),
    path('management/activity-logs/', AdminLogsView.as_view(), name='admin-logs'),
    path('management/settings/',    AdminSettingsView.as_view(), name='admin-settings'),

    # Driver
    path('driver-dashboard/',  DriverDashboardView.as_view(),  name='driver-dashboard'),
]
