from django.urls import path

from .views import (
    ChangePasswordView,
    CustomTokenObtainPairView,
    LogoutView,
    ProfileView,
    RegisterView,
    SessionLoginView,
    UserListView,
)

urlpatterns = [
    path('login/',           CustomTokenObtainPairView.as_view(),  name='auth-login'),
    path('register/',        RegisterView.as_view(),              name='auth-register'),
    path('logout/',          LogoutView.as_view(),                name='auth-logout'),
    path('profile/',         ProfileView.as_view(),               name='auth-profile'),
    path('change-password/', ChangePasswordView.as_view(),        name='auth-change-password'),
    path('users/',           UserListView.as_view(),              name='auth-user-list'),
    path('session-login/',  SessionLoginView.as_view(), name='session-login'),
]