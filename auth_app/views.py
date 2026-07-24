from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, logout as django_logout
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserSerializer,
)
from django.contrib.auth import authenticate
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