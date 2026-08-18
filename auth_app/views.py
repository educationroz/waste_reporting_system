from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, logout as django_logout
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

import json as _json
import urllib.parse as _urlparse
import urllib.request as _urlrequest

User = get_user_model()


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


class SessionLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            return Response({'message': 'Session created.'})
        return Response({'error': 'Invalid credentials.'}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class CustomTokenObtainPairView(TokenObtainPairView):
    """Login — returns access + refresh tokens plus user info."""
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]


@method_decorator(csrf_exempt, name='dispatch')
class CustomTokenRefreshView(TokenRefreshView):
    """Exchanges a valid refresh token for a new access token.

    base.html's apiFetch() calls this automatically when a request comes
    back 401, so a session keeps working past the 1-hour access token
    lifetime without bouncing the user to the login page.
    """
    permission_classes = [AllowAny]


class GoogleLoginView(APIView):
    """Signs a user in with a Google ID token and returns our own JWTs.

    NOTE: POST only. Do not point Google's `data-login_uri` at this URL —
    that performs a redirect (GET) and will 405. Use the JS callback and
    fetch() this endpoint instead.
    """
    permission_classes = [AllowAny]

    GOOGLE_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'

    def post(self, request):
        credential = request.data.get('credential') or request.data.get('id_token')
        if not credential:
            return Response({'error': 'Missing Google credential.'},
                            status=status.HTTP_400_BAD_REQUEST)

        client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
        if not client_id:
            return Response({'error': 'Google sign-in is not configured on this server.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # --- verify the token with Google -------------------------------
        try:
            url = f'{self.GOOGLE_TOKENINFO_URL}?{_urlparse.urlencode({"id_token": credential})}'
            with _urlrequest.urlopen(url, timeout=10) as resp:
                payload = _json.loads(resp.read().decode('utf-8'))
        except Exception:
            # Covers HTTP 400 (invalid/expired token) and network failures
            # alike; never leak the raw error to the client.
            return Response({'error': 'Could not verify Google account. Please try again.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        # aud must be OUR client id, or a token minted for another app
        # could be replayed against this endpoint.
        if payload.get('aud') != client_id:
            return Response({'error': 'This Google token was not issued for this application.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        email = (payload.get('email') or '').strip().lower()
        if not email:
            return Response({'error': 'Google account has no email address.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if str(payload.get('email_verified')).lower() not in ('true', '1'):
            return Response({'error': 'This Google email is not verified.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # --- find or create the local user ------------------------------
        user = User.objects.filter(email__iexact=email).first()
        created = False
        if user is None:
            base_username = email.split('@')[0][:140] or 'user'
            username = base_username
            n = 1
            while User.objects.filter(username=username).exists():
                n += 1
                username = f'{base_username}{n}'[:150]

            user = User(
                username=username,
                email=email,
                first_name=(payload.get('given_name') or '')[:150],
                last_name=(payload.get('family_name') or '')[:150],
                role='user',      # never trust the client for role
                is_active=True,   # Google already proved the email
                is_verified=True,
            )
            user.set_unusable_password()  # no local password to brute-force
            user.save()
            created = True
        elif not user.is_active:
            return Response({'error': 'This account is disabled.'},
                            status=status.HTTP_403_FORBIDDEN)

        # Create a Django SESSION as well as JWTs.
        #
        # The password flow does this by calling /auth/session-login/ after
        # login. Google users never hit that endpoint, and every page view in
        # web_app uses LoginRequiredMixin (session-based) rather than JWT — so
        # without this a Google user gets valid tokens, is redirected to the
        # dashboard, and is immediately bounced back to /login/.
        #
        # backend= is required because authenticate() was never called, so
        # Django cannot infer which auth backend to record on the session.
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        refresh = RefreshToken.for_user(user)
        refresh['username'] = user.username
        refresh['email'] = user.email
        refresh['role'] = user.role

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
            'created': created,
        })


class RegisterView(generics.CreateAPIView):
    """Register a new user. No auth required. Sends an email verification link."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

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


class VerifyEmailView(APIView):
    """Confirms a user's email from the link sent at registration."""
    permission_classes = [AllowAny]

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


class ResendVerificationEmailView(APIView):
    """Re-sends the verification email for an unverified account."""
    permission_classes = [AllowAny]

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


class PasswordResetRequestView(APIView):
    """Step 1 of forgot-password: submit an email, get a reset link emailed."""
    permission_classes = [AllowAny]

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


class PasswordResetConfirmView(APIView):
    """Step 2 of forgot-password: submit uid/token from the email plus a new password."""
    permission_classes = [AllowAny]

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


class LogoutView(APIView):
    """Logs out JWT/session users. Blacklists refresh token when provided."""
    permission_classes = [AllowAny]

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


class ProfileView(generics.RetrieveUpdateAPIView):
    """Get or update current user's profile."""
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """Change password. Requires current password for verification."""
    permission_classes = [IsAuthenticated]

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


class UserListView(generics.ListAPIView):
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