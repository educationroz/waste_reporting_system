from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from email_validator import EmailNotValidError, validate_email
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['email'] = user.email
        token['role'] = user.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'role': self.user.role,
            'phone': self.user.phone,
        }
        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'password2',
            'role', 'phone', 'address',
        )
        extra_kwargs = {
            'email': {'required': True},
            'role': {'read_only': True},
        }

    def validate_email(self, value):
        """Reject malformed emails and, in production, domains with no valid MX record."""
        check_deliverability = getattr(
            settings, 'EMAIL_CHECK_DELIVERABILITY', not settings.DEBUG
        )
        try:
            emailinfo = validate_email(value, check_deliverability=check_deliverability)
            value = emailinfo.normalized
        except EmailNotValidError as e:
            raise serializers.ValidationError(str(e))
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        # Case-insensitive: User.save() lowercases email, so 'Foo@x.com' and
        # 'foo@x.com' must be treated as the same account, not slipped past an
        # exact-match filter that can't see the normalized stored value.
        if User.objects.filter(email__iexact=attrs['email']).exists():
            raise serializers.ValidationError({'email': 'Email already in use.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')
        # Defense-in-depth: override role to 'user' regardless of what was
        # submitted. Even if the serializer-level read_only is bypassed
        # (e.g. a future code change removes extra_kwargs), this server-side
        # guarantee prevents privilege escalation via the registration API.
        validated_data['role'] = 'user'
        user = User(**validated_data)
        user.set_password(password)
        # Account stays inactive/unverified until the emailed link is clicked.
        # authenticate() already refuses inactive users, so login/token
        # endpoints are blocked automatically without any extra checks there.
        user.is_active = False
        user.is_verified = False
        user.save()

        # Driver profile is auto-created by auth_app.signals.sync_driver_profile
        # after the user is saved, so this serializer should not create it again.
        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name',
            'role', 'phone', 'address', 'profile_picture',
            'is_verified', 'date_joined',
        )
        read_only_fields = (
            'id', 'date_joined', 'is_verified',
            # role/username/email are identity-critical: only admins create/
            # manage accounts (api_app.AdminUserCreateView/UpdateView), never a
            # self-service PATCH. ProfileView uses this serializer, so a user
            # could otherwise PATCH {"role": "admin"} and escalate to admin.
            'role', 'username', 'email',
        )


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password': 'New passwords do not match.'})
        return attrs

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    """Step 1 of forgot-password: user submits their email."""
    email = serializers.EmailField(required=True)


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Step 2 of forgot-password: user submits the uid/token from the emailed
    link plus their new password."""
    uidb64 = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password': 'Passwords do not match.'})
        return attrs