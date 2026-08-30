import json as _json
import urllib.parse as _urlparse
import urllib.request as _urlrequest

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .tokens import email_verification_token

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
    """Primary browser login: sets the HttpOnly session cookie.

    SECURITY: the browser UI uses this instead of the JWT endpoint so no
    token is ever readable from JavaScript. It returns the user payload the
    login page needs for its post-login role redirect, but deliberately
    returns no access/refresh token.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'session_login'

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            return Response({
                'message': 'Session created.',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': getattr(user, 'role', ''),
                },
            })
        return Response({'error': 'Invalid credentials.'}, status=400)


class BiometricRegisterTokenView(APIView):
    """Generates a secure signed token for biometric authentication on the current device."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        signer = TimestampSigner(salt='biometric-auth')
        signed_token = signer.sign(f"{request.user.id}:{request.user.username}")
        user = request.user
        profile_pic_url = user.profile_picture.url if getattr(user, 'profile_picture', None) else ''
        role_display = user.get_role_display() if hasattr(user, 'get_role_display') else getattr(user, 'role', '')
        return Response({
            'message': 'Biometric token generated.',
            'token': signed_token,
            'username': user.username,
            'user_id': user.id,
            'email': user.email,
            'role': getattr(user, 'role', ''),
            'role_display': role_display,
            'full_name': user.get_full_name() or user.username,
            'profile_picture': profile_pic_url,
        })


class BiometricLoginView(APIView):
    """Passwordless login using device biometric verification."""
    permission_classes = [AllowAny]
    throttle_scope = 'session_login'

    def post(self, request):
        username = request.data.get('username')
        token = request.data.get('token')

        if not username or not token:
            return Response({'error': 'Username and biometric token required.'}, status=status.HTTP_400_BAD_REQUEST)

        signer = TimestampSigner(salt='biometric-auth')
        try:
            unsigned_value = signer.unsign(token, max_age=60 * 60 * 24 * 90)
            user_id_str, token_username = unsigned_value.split(':', 1)
        except (BadSignature, SignatureExpired, ValueError):
            return Response({'error': 'Biometric token expired or invalid. Please sign in with password to re-enable.'}, status=status.HTTP_401_UNAUTHORIZED)

        if token_username.lower() != username.strip().lower():
            return Response({'error': 'Biometric token user mismatch.'}, status=status.HTTP_401_UNAUTHORIZED)

        user = User.objects.filter(id=user_id_str, username__iexact=username).first()
        if not user or not user.is_active:
            return Response({'error': 'Account not found or inactive.'}, status=status.HTTP_401_UNAUTHORIZED)

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        profile_pic_url = user.profile_picture.url if getattr(user, 'profile_picture', None) else ''
        role_display = user.get_role_display() if hasattr(user, 'get_role_display') else getattr(user, 'role', '')
        return Response({
            'message': 'Biometric login successful.',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': getattr(user, 'role', ''),
                'role_display': role_display,
                'full_name': user.get_full_name() or user.username,
                'profile_picture': profile_pic_url,
            },
        })


class ExportUserDataView(APIView):
    """Allows user to export and download their complete profile, waste requests, and complaints."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        from api_app.models import Complaint, WasteRequest

        user_data = {
            'exported_at': timezone.now().isoformat(),
            'account_info': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'phone': getattr(user, 'phone', ''),
                'address': getattr(user, 'address', ''),
                'role': getattr(user, 'role', ''),
                'is_verified': getattr(user, 'is_verified', False),
                'date_joined': user.created_at.isoformat() if hasattr(user, 'created_at') else None,
            },
            'waste_requests': [],
            'complaints': [],
        }

        reqs = WasteRequest.objects.filter(user=user).order_by('-created_at')
        for r in reqs:
            user_data['waste_requests'].append({
                'id': r.id,
                'waste_type': r.waste_type,
                'status': r.status,
                'pickup_address': r.pickup_address,
                'latitude': float(r.latitude) if r.latitude else None,
                'longitude': float(r.longitude) if r.longitude else None,
                'notes': r.notes,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'completed_at': r.completed_at.isoformat() if r.completed_at else None,
            })

        complaints = Complaint.objects.filter(user=user).order_by('-created_at')
        for c in complaints:
            user_data['complaints'].append({
                'id': c.id,
                'complaint_type': c.complaint_type,
                'subject': c.subject,
                'description': c.description,
                'status': c.status,
                'created_at': c.created_at.isoformat() if c.created_at else None,
            })

        response = HttpResponse(
            _json.dumps(user_data, indent=2),
            content_type='application/json'
        )
        filename = f"safhasahar_account_{user.username}_{timezone.now().strftime('%Y%m%d')}.json"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


@method_decorator(csrf_exempt, name='dispatch')
class CustomTokenObtainPairView(TokenObtainPairView):
    """Login — returns access + refresh tokens plus user info."""
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'login'


@method_decorator(csrf_exempt, name='dispatch')
class CustomTokenRefreshView(TokenRefreshView):
    """Exchanges a valid refresh token for a new access token.

    base.html's apiFetch() calls this automatically when a request comes
    back 401, so a session keeps working past the 1-hour access token
    lifetime without bouncing the user to the login page.
    """
    permission_classes = [AllowAny]
    throttle_scope = 'token_refresh'


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

        client_id = str(getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '') or '').strip().strip('"\'')
        if not client_id:
            return Response({'error': 'Google sign-in is not configured on this server.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # --- verify the token with Google -------------------------------
        payload = None
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
            payload = google_id_token.verify_oauth2_token(
                credential, google_requests.Request(), client_id
            )
        except Exception:
            try:
                url = f'{self.GOOGLE_TOKENINFO_URL}?{_urlparse.urlencode({"id_token": credential})}'
                with _urlrequest.urlopen(url, timeout=10) as resp:
                    payload = _json.loads(resp.read().decode('utf-8'))
                # Require aud to match our client_id. `azp` ("authorized
                # presenter") can legitimately differ from the audience in some
                # flows, so accepting an azp-only match weakened the check.
                if payload.get('aud') != client_id:
                    return Response({'error': 'This Google token was not issued for this application.'},
                                    status=status.HTTP_401_UNAUTHORIZED)
            except Exception:
                # Covers HTTP 400 (invalid/expired token) and network failures
                # alike; never leak the raw error to the client.
                return Response({'error': 'Could not verify Google account. Please try again.'},
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


class VerifyEmailView(APIView):
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


class ResendVerificationEmailView(APIView):
    """Re-sends the verification email for an unverified account."""
    permission_classes = [AllowAny]
    throttle_scope = 'resend_verification'

    def post(self, request):
        email = request.data.get('email')
        user = User.objects.filter(email__iexact=email).first()
        if user is None or user.is_verified:
            # One identical message for "no such account" AND "already
            # verified" — otherwise this endpoint is an oracle that lets
            # anyone confirm whether any email is registered on the site.
            return Response({'message': 'If that account exists and is unverified, an email has been sent.'})

        send_verification_email(user, request)
        return Response({'message': 'If that account exists and is unverified, an email has been sent.'})


class PasswordResetRequestView(APIView):
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

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return generic_response

        send_password_reset_email(user, request)
        return generic_response


class PasswordResetConfirmView(APIView):
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


class LogoutView(APIView):
    """Logs out JWT/session users. Blacklists refresh token when provided.

    SECURITY: requires authentication. This endpoint mutates session/token
    state (ends the caller's own session, blacklists their own refresh
    token) — there's no legitimate reason for an anonymous caller to hit
    it, and leaving it open is an unnecessary attack surface (e.g. in
    combination with session-fixation attempts, or simply as noise for
    anyone probing the API).
    """
    permission_classes = [IsAuthenticated]
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


class ProfileView(generics.RetrieveUpdateAPIView):
    """Get or update current user's profile."""
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
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