from rest_framework import serializers
from .models import Report, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role']


class ReportSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            'id', 'user', 'title', 'description',
            'image', 'image_url', 'latitude', 'longitude',
            'status', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'status', 'created_at', 'updated_at']
        extra_kwargs = {
            'image': {'write_only': True, 'required': False},
        }

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

    def validate(self, data):
        lat = data.get('latitude')
        lon = data.get('longitude')
        if lat is not None and not (-90 <= float(lat) <= 90):
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        if lon is not None and not (-180 <= float(lon) <= 180):
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return data


class ReportStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ['status']

    def validate_status(self, value):
        allowed = [choice[0] for choice in Report.STATUS_CHOICES]
        if value not in allowed:
            raise serializers.ValidationError(f"Status must be one of: {allowed}")
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, label="Confirm Password")

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        return data

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            role='user',
        )
        return user