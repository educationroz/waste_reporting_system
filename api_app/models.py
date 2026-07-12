from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator


class Vehicle(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('on_route', 'On Route'),
        ('maintenance', 'Under Maintenance'),
        ('inactive', 'Inactive'),
    ]
    TYPE_CHOICES = [
        ('truck', 'Garbage Truck'),
        ('van', 'Van'),
        ('compactor', 'Compactor'),
    ]

    plate_number = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='truck')
    capacity_kg = models.FloatField(default=0.0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', db_index=True)
    last_service_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vehicles'
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['vehicle_type', 'status']),
        ]

    def __str__(self):
        return f"{self.plate_number} ({self.vehicle_type})"


class Driver(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='driver_profile',
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_drivers',
    )
    license_number = models.CharField(max_length=50, unique=True)
    is_available = models.BooleanField(default=True, db_index=True)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    total_trips = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'drivers'
        indexes = [
            models.Index(fields=['is_available', 'vehicle']),
            models.Index(fields=['is_available', '-created_at']),
        ]

    def __str__(self):
        return f"Driver: {self.user.username}"


class Bin(models.Model):
    TYPE_CHOICES = [
        ('general', 'General Waste'),
        ('recyclable', 'Recyclable'),
        ('organic', 'Organic'),
        ('hazardous', 'Hazardous'),
    ]
    STATUS_CHOICES = [
        ('empty', 'Empty'),
        ('half_full', 'Half Full'),
        ('full', 'Full'),
        ('overflow', 'Overflow'),
    ]

    bin_code = models.CharField(max_length=30, unique=True)
    waste_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='general')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='empty')
    capacity_liters = models.FloatField(default=240.0)
    location_address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    last_emptied = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bins'
        indexes = [
            models.Index(fields=['status', 'waste_type']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['waste_type']),
        ]

    def __str__(self):
        return f"{self.bin_code} ({self.waste_type}) - {self.status}"


class WasteRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    WASTE_TYPE_CHOICES = [
        ('general', 'General Waste'),
        ('recyclable', 'Recyclable'),
        ('organic', 'Organic'),
        ('bulky', 'Bulky Item'),
        ('hazardous', 'Hazardous'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='waste_requests',
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_requests',
    )
    waste_type = models.CharField(max_length=20, choices=WASTE_TYPE_CHOICES, default='general')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    description = models.TextField(blank=True)
    pickup_address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    photo = models.ImageField(
        upload_to='waste_photos/',
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp'])
        ],
        help_text='Accepted formats: JPG, JPEG, PNG, GIF, WebP (Max 5MB)'
    )
    photo_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    photo_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    scheduled_date = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'waste_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'scheduled_date']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['driver', 'status']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"Request #{self.id} - {self.user.username} ({self.status})"


class Route(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='routes',
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='routes',
    )
    waste_requests = models.ManyToManyField(
        WasteRequest, blank=True, related_name='routes'
    )
    bins = models.ManyToManyField(Bin, blank=True, related_name='routes')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    planned_date = models.DateField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_distance_km = models.FloatField(default=0.0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'routes'
        ordering = ['-planned_date']
        indexes = [
            models.Index(fields=['driver', 'status']),
            models.Index(fields=['vehicle', 'status']),
            models.Index(fields=['status', '-planned_date']),
        ]

    def __str__(self):
        return f"Route #{self.id} - {self.planned_date} ({self.status})"


class Schedule(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-Weekly'),
        ('monthly', 'Monthly'),
    ]

    DAY_OF_WEEK_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    zone_name = models.CharField(max_length=100)
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedules',
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedules',
    )
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='weekly')
    day_of_week = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=DAY_OF_WEEK_CHOICES,
        help_text='0=Monday, 6=Sunday'
    )
    start_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'schedules'
        indexes = [
            models.Index(fields=['driver', 'is_active']),
            models.Index(fields=['vehicle', 'is_active']),
            models.Index(fields=['is_active', 'zone_name']),
        ]

    def __str__(self):
        return f"Schedule: {self.zone_name} ({self.frequency})"


class Notification(models.Model):
    TYPE_CHOICES = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('success', 'Success'),
        ('alert', 'Alert'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='info')
    is_read = models.BooleanField(default=False, db_index=True)
    related_request = models.ForeignKey(
        WasteRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['is_read', '-created_at']),
        ]

    def __str__(self):
        return f"Notification for {self.user.username}: {self.title}"


class AdminLog(models.Model):
    """Log admin actions for audit trail."""
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('assign', 'Assign'),
        ('status_change', 'Status Change'),
        ('login', 'Login'),
        ('permission_change', 'Permission Change'),
        ('other', 'Other'),
    ]

    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='admin_logs',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    content_type = models.CharField(max_length=50)  # e.g., 'Driver', 'Vehicle', 'WasteRequest'
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_description = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)  # Store before/after values
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'admin_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['admin_user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f"{self.admin_user.username if self.admin_user else 'Unknown'} - {self.action} on {self.content_type}"


class SystemSettings(models.Model):
    """Store system-wide configuration settings."""
    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    description = models.TextField(blank=True)
    is_sensitive = models.BooleanField(default=False)  # Hide sensitive values in logs
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settings_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'system_settings'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return f"{self.key}: {self.value}"
    
class Complaint(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"Complaint by {self.user.username}: {self.subject}"