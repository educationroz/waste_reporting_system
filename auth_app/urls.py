from django.urls import path

from .views import *

urlpatterns = [
    path('login/',           CustomTokenObtainPairView.as_view(),  name='auth-login'),
    path('google-login/',    GoogleLoginView.as_view(),            name='auth-google-login'),
    path('token/refresh/',   CustomTokenRefreshView.as_view(),     name='auth-token-refresh'),
    path('register/',        RegisterView.as_view(),              name='auth-register'),
    path('logout/',          LogoutView.as_view(),                name='auth-logout'),
    path('profile/',         ProfileView.as_view(),               name='auth-profile'),
    path('change-password/', ChangePasswordView.as_view(),        name='auth-change-password'),
    path('users/',           UserListView.as_view(),              name='auth-user-list'),
    path('session-login/',  SessionLoginView.as_view(), name='session-login'),
    path('biometric-register-token/', BiometricRegisterTokenView.as_view(), name='biometric-register-token'),
    path('biometric-login/',          BiometricLoginView.as_view(),          name='biometric-login'),
    path('export-data/',              ExportUserDataView.as_view(),          name='export-user-data'),
    path('verify-email/<str:uidb64>/<str:token>/', VerifyEmailView.as_view(), name='verify-email'),
    path('resend-verification/', ResendVerificationEmailView.as_view(), name='resend-verification'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password-reset-confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
]