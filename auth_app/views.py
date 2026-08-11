from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, logout as django_logout
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)
from django.contrib.auth import authenticate
from .tokens import email_verification_token

User = get_user_model()


# ─── Scope-default throttling helpers ────────────────────────────────────────
# Mixins so AllowAny views get throttled by anon IP, and authenticated views
# by user PK. Each subclass just sets `throttle_scope = '…'` to pick the rate
# defined in settings.REST_FRAMEWORK.DEFAULT_THROTTLE_RATES.
class AnonScopedThrottleMixin:
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]

class AuthScopedThrottleMixin:
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]


def send_verification_email(user, request):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verify_path = f'/auth/verify-email/{uid}/{token}/'
    verify_url = request.build_absolute_uri(verify_path)

    send_mail(
        subject='Verify your email — Waste Collection',
        message=(
            f'Hi {user.username},\n\n'
            f'Please confirm your email address by clicking the link below:\n'
            f'{verify_url}\n\n'
            f'If you did not create this account, you can ignore this email.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_password_reset_email(user, request):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    # Frontend route — adjust the path to wherever your reset-password page
    # actually lives; it should read uid/token from the URL and POST them
    # (along with the new password) to /auth/password-reset-confirm/.
    reset_path = f'/reset-password/{uid}/{token}/'
    reset_url = request.build_absolute_uri(reset_path)

    send_mail(
        subject='Reset your password — Waste Collection',
        message=(
            f'Hi {user.username},\n\n'
            f'We received a request to reset your password. Click the link below to choose a new one:\n'
            f'{reset_url}\n\n'
            f'This link will expire after a short time and can only be used once.\n'
            f'If you did not request this, you can safely ignore this email — your password will not change.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


class SessionLoginView(AnonScopedThrottleMixin, APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'session_login'

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            return Response({'message': 'Session created.'})
        return Response({'error': 'Invalid credentials.'}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class CustomTokenObtainPairView(AnonScopedThrottleMixin, TokenObtainPairView):
    """Login — returns access + refresh tokens plus user info."""
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'login'


class GoogleLoginView(AnonScopedThrottleMixin, APIView):
    """
    Google Sign-In. The frontend sends the Google ID token (a JWT) it
    receives from Google's Identity Services button. We verify that token
    directly with Google's own servers (so it can't be forged), then
    find-or-create a local User and issue our own access/refresh JWT pair —
    exactly like a normal username/password login.
    """
    permission_classes = [AllowAny]
    throttle_scope = 'login'  # reuse the same 5/min throttle as normal login

    def post(self, request):
        credential = request.data.get('credential')
        if not credential:
            return Response({'error': 'No Google credential provided.'}, status=400)

        try:
            idinfo = google_id_token.verify_oauth2_token(
                credential,
                google_auth_requests.Request(),
                settings.GOOGLE_OAUTH_CLIENT_ID,
            )
        except ValueError:
            # Token was malformed, expired, or its audience didn't match
            # our Client ID — never trust it in that case.
            return Response({'error': 'Invalid or expired Google token.'}, status=400)

        email = idinfo.get('email')
        email_verified = idinfo.get('email_verified')
        if not email or not email_verified:
            return Response({'error': 'Google account has no verified email.'}, status=400)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # New account — auto-provision it. Google has already verified
            # the email address for us, so we skip our own verification
            # email step entirely for Google sign-ups.
            base_username = (email.split('@')[0] or 'user')[:20]
            username = base_username
            suffix = 1
            while User.objects.filter(username=username).exists():
                username = f'{base_username}{suffix}'
                suffix += 1

            user = User(
                username=username,
                email=email,
                role='user',
                is_verified=True,
                is_active=True,
            )
            user.set_unusable_password()  # this account can only sign in via Google
            user.save()

        if not user.is_active:
            return Response({'error': 'This account is inactive.'}, status=400)

        refresh = RefreshToken.for_user(user)

        # Also establish the Django session, matching what the normal
        # username/password flow does via /auth/session-login/. Google
        # users have no password for that endpoint to check against, so we
        # log the session in directly here instead.
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })


class RegisterView(AnonScopedThrottleMixin, generics.CreateAPIView):
    """Register a new user. No auth required. Sends an email verification link."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'register'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        send_verification_email(user, request)

        return Response(
            {
                'user': UserSerializer(user).data,
                'message': 'Account created. Please check your email to verify your account before logging in.',
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(AnonScopedThrottleMixin, APIView):
    """Confirms a user's email from the link sent at registration."""
    permission_classes = [AllowAny]
    throttle_scope = 'verify_email'

    def get(self, request, uidb64, token):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is not None and email_verification_token.check_token(user, token):
            user.is_verified = True
            user.is_active = True
            user.save()
            return Response({'message': 'Email verified successfully. You can now log in.'})

        return Response({'error': 'This verification link is invalid or has expired.'}, status=400)


class ResendVerificationEmailView(AnonScopedThrottleMixin, APIView):
    """Re-sends the verification email for an unverified account."""
    permission_classes = [AllowAny]
    throttle_scope = 'resend_verification'

    def post(self, request):
        email = request.data.get('email')
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Don't reveal whether the email exists.
            return Response({'message': 'If that account exists and is unverified, an email has been sent.'})

        if user.is_verified:
            return Response({'message': 'This account is already verified.'})

        send_verification_email(user, request)
        return Response({'message': 'If that account exists and is unverified, an email has been sent.'})


class PasswordResetRequestView(AnonScopedThrottleMixin, APIView):
    """Step 1 of forgot-password: submit an email, get a reset link emailed."""
    permission_classes = [AllowAny]
    throttle_scope = 'password_reset_request'

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Always return the same generic message whether or not the account
        # exists — this prevents attackers from using this endpoint to
        # discover which emails are registered.
        generic_response = Response(
            {'message': 'If an account with that email exists, a password reset link has been sent.'}
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        send_password_reset_email(user, request)
        return generic_response


class PasswordResetConfirmView(AnonScopedThrottleMixin, APIView):
    """Step 2 of forgot-password: submit uid/token from the email plus a new password."""
    permission_classes = [AllowAny]
    throttle_scope = 'password_reset_confirm'

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            uid = force_str(urlsafe_base64_decode(data['uidb64']))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, data['token']):
            return Response(
                {'error': 'This password reset link is invalid or has expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(data['new_password'])
        user.save()
        return Response({'message': 'Password has been reset successfully. You can now log in.'})


class LogoutView(AnonScopedThrottleMixin, APIView):
    """Logs out JWT/session users. Blacklists refresh token when provided."""
    permission_classes = [AllowAny]
    throttle_scope = 'logout'

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                # Token may already be invalid/expired; continue with session logout.
                pass

        django_logout(request)
        return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)


class ProfileView(AuthScopedThrottleMixin, generics.RetrieveUpdateAPIView):
    """Get or update current user's profile."""
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    # Uses DEFAULT_THROTTLE_RATES['user'] from settings.
    # No need for a tighter scope — profile writes are infrequent and owned.

    def get_object(self):
        # "My profile" endpoint — always the logged-in user, never looked up
        # by a URL param/queryset filter. Without this, DRF's default
        # get_object() tries self.get_queryset(), which isn't defined here,
        # and raises an AssertionError → surfaces to the client as an
        # unhandled 500 on every GET/PATCH to this endpoint.
        return self.request.user


class ChangePasswordView(AuthScopedThrottleMixin, APIView):
    """Change password. Requires current password for verification."""
    permission_classes = [IsAuthenticated]
    throttle_scope = 'change_password'

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'message': 'Password changed successfully.'},
            status=status.HTTP_200_OK,
        )


class CustomTokenRefreshView(AnonScopedThrottleMixin, TokenRefreshView):
    """JWT refresh endpoint — returns a new access token (and rotated refresh).

    Keyed by anon IP because at the time refresh_token is submitted, the caller
    has NO valid Authorization access token yet.
    """
    throttle_scope = 'token_refresh'


class UserListView(AuthScopedThrottleMixin, generics.ListAPIView):
    """Admin-only: list all users."""
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_admin:
            return User.objects.none()
        role = self.request.query_params.get('role')
        qs = User.objects.all().order_by('-date_joined')
        if role:
            qs = qs.filter(role=role)
        return qs