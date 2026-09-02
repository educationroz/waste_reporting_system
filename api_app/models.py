from django.conf import settings
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.utils.translation import gettext_lazy as _

from .validators import validate_image_file, validate_pdf_file


class Vehicle(models.Model):
    STATUS_CHOICES = [
        ('available', _('Available')),
        ('on_route', _('On Route')),
        ('maintenance', _('Under Maintenance')),
        ('inactive', _('Inactive')),
    ]
    # Base/legacy types — still used as the default suggestions in the UI,
    # but vehicle_type itself is now free text (no `choices=` enforcement),
    # so admins can add their own custom vehicle types beyond this list.
    TYPE_CHOICES = [
        ('truck', _('Garbage Truck')),
        ('van', _('Van')),
        ('compactor', _('Compactor')),
    ]

    plate_number = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=50, default='truck')
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


class VehicleType(models.Model):
    """
    Manageable list of vehicle type options shown in the Add/Edit Vehicle
    dropdowns. This is purely a picklist — Vehicle.vehicle_type stores
    whatever string was chosen directly (it's a plain CharField, not a
    ForeignKey to this table), so deleting an entry here only removes it
    from future suggestions; it never touches or breaks existing Vehicle
    rows that already have that type set.
    """
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vehicle_types'
        ordering = ['id']

    def __str__(self):
        return self.name


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
    license_document = models.FileField(
        upload_to='driver_licenses/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['pdf']), validate_pdf_file],
        help_text='Driving license document (PDF only, max 5MB)'
    )

    # ── Break / shift management ──────────────────────────────────────
    # Driver marks themselves On Break (lunch, fuel, rest). While on break the
    # driver is NOT available (is_available stays False). The reason + start
    # timestamp are recorded, and each break session is logged in
    # DriverBreakLog for an audit trail / analytics.
    on_break = models.BooleanField(
        default=False,
        help_text='True while the driver has marked themselves on a break.'
    )
    break_reason = models.CharField(
        max_length=50, blank=True, null=True,
        help_text='Optional reason for the current break (lunch, fuel, rest, other).'
    )
    break_started_at = models.DateTimeField(
        blank=True, null=True,
        help_text='When the current break session started.'
    )

    class Meta:
        db_table = 'drivers'
        indexes = [
            models.Index(fields=['is_available', 'vehicle']),
            models.Index(fields=['is_available', '-created_at']),
            models.Index(fields=['is_available', 'on_break']),
            models.Index(fields=['on_break', '-break_started_at']),
        ]

    def __str__(self):
        return f"Driver: {self.user.username}"


class DriverBreakLog(models.Model):
    """One logged break session. Written on break start, closed on break end."""
    REASON_CHOICES = [
        ('lunch', _('Lunch')),
        ('fuel', _('Fuel')),
        ('rest', _('Rest')),
        ('other', _('Other')),
    ]

    driver = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name='break_logs'
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='other')
    note = models.CharField(max_length=50, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'driver_break_logs'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['driver', '-started_at']),
            models.Index(fields=['driver', 'ended_at']),
        ]

    def __str__(self):
        return f"Break for {self.driver.user.username} ({self.get_reason_display()})"


class Bin(models.Model):
    TYPE_CHOICES = [
        ('general', _('General Waste')),
        ('recyclable', _('Recyclable')),
        ('organic', _('Organic')),
        ('hazardous', _('Hazardous')),
    ]
    STATUS_CHOICES = [
        ('empty', _('Empty')),
        ('half_full', _('Half Full')),
        ('full', _('Full')),
        ('overflow', _('Overflow')),
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


class Checkpoint(models.Model):
    """Admin-defined designated waste drop-off locations."""
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'checkpoints'
        verbose_name = 'Checkpoint'
        verbose_name_plural = 'Checkpoints'
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.latitude}, {self.longitude})"


class WasteRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('assigned', _('Assigned')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    ]
    WASTE_TYPE_CHOICES = [
        ('general', _('General Waste')),
        ('recyclable', _('Recyclable')),
        ('organic', _('Organic')),
        ('bulky', _('Bulky Item')),
        ('hazardous', _('Hazardous')),
    ]
    SEVERITY_CHOICES = [
        ('low', _('Low')),
        ('medium', _('Medium')),
        ('high', _('High')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='waste_requests',
    )
    submitting_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='shared_waste_requests',
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
    dropoff_checkpoint = models.ForeignKey(
        'Checkpoint', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='waste_requests'
    )
    # FIX: this previously had WasteRequestPhoto's upload_to path
    # ('waste_photos/extra/') pasted in, and was missing blank=True/null=True
    # — that made every WasteRequest require a photo at the DB level (guest
    # reports with no photo would fail to save) and filed primary photos
    # into the "extra" subfolder instead of their own.
    photo = models.ImageField(
        upload_to='waste_photos/',
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp']),
            validate_image_file,
        ],
        help_text='Accepted formats: JPG, JPEG, PNG, GIF, WebP (Max 5MB)'
    )
    photo_latitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    photo_longitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])


    # ── Completion GPS verification ──────────────────────────────────
    # Driver ले "Completed" mark गर्ने बेला उनको वास्तविक GPS यहाँ save हुन्छ।
    # Pickup location बाट टाढा भए completion_flagged=True हुन्छ — admin ले
    # यही flag हेरेर driver लाई कारवाही/warning गर्न सक्छ।
    completion_latitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text="Driver's GPS location captured when marking this request completed.")
    completion_longitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    completion_distance_meters = models.FloatField(
        null=True, blank=True,
        help_text="Distance (meters) between driver's completion GPS and the reported pickup location.")
    completion_flagged = models.BooleanField(
        default=False, db_index=True,
        help_text="True if driver completed >500m away from pickup location — needs admin review.")

    # ── Guest submission claiming ──────────────────────────────────
    guest_token = models.CharField(
        max_length=64, blank=True, null=True, db_index=True,
        help_text='Random token set client-side when a guest (not logged in) '
                   'submits a request, so it can later be claimed/linked to '
                   'their account once they register or log in.'
    )
    guest_email = models.EmailField(
        blank=True, null=True, db_index=True, max_length=254,
        help_text='Optional email a guest provides at submission time. It is a '
                   'backup claim channel: if the browser-stored guest_token is '
                   'lost (cleared browser data, switched devices), registering '
                   'or logging in with this email automatically links these '
                   'requests to that account.'
    )

    # ── ML Gatekeeper Classification (auto-filled on photo upload) ──────
    severity = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, blank=True, null=True,
        help_text='Auto-detected waste severity from the gatekeeper ML model.'
    )
    ml_confidence = models.FloatField(
        blank=True, null=True,
        help_text='ML model confidence percentage (0-100) for the severity prediction.'
    )
    needs_manual_review = models.BooleanField(
        default=False,
        help_text='True if ML confidence was below the review threshold — admin should verify manually.'
    )

    scheduled_date = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

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
        username = self.user.username if self.user else "Guest"
        return f"Request #{self.id} - {username} ({self.status})"


class WasteRequestPhoto(models.Model):
    """
    WasteRequest sanga jodिएका extra photo haru — user ले multiple photo
    upload/capture garda pahilo photo chai WasteRequest.photo field ma
    janchha (backward compatible), baँki sabai yaha save huन्छन्.
    """
    request = models.ForeignKey(
        WasteRequest,
        on_delete=models.CASCADE,
        related_name='extra_photos',
    )
    photo = models.ImageField(
        upload_to='waste_photos/extra/',
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp']),
            validate_image_file,
        ],
    )
    latitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'waste_request_photos'
        ordering = ['created_at']

    def __str__(self):
        return f"Photo for Request #{self.request_id}"


class Route(models.Model):
    STATUS_CHOICES = [
        ('planned', _('Planned')),
        ('active', _('Active')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
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
        constraints = [
            models.UniqueConstraint(
                fields=['driver', 'planned_date', 'status'],
                condition=models.Q(status='planned'),
                name='unique_planned_route_per_driver_per_day',
            ),
        ]
        indexes = [
            models.Index(fields=['driver', 'status']),
            models.Index(fields=['vehicle', 'status']),
            models.Index(fields=['status', '-planned_date']),
        ]

    def __str__(self):
        return f"Route #{self.id} - {self.planned_date} ({self.status})"


class Schedule(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', _('Daily')),
        ('weekly', _('Weekly')),
        ('biweekly', _('Bi-Weekly')),
        ('monthly', _('Monthly')),
    ]

    DAY_OF_WEEK_CHOICES = [
        (0, _('Monday')),
        (1, _('Tuesday')),
        (2, _('Wednesday')),
        (3, _('Thursday')),
        (4, _('Friday')),
        (5, _('Saturday')),
        (6, _('Sunday')),
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
        ('info', _('Information')),
        ('warning', _('Warning')),
        ('success', _('Success')),
        ('alert', _('Alert')),
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
        ('create', _('Create')),
        ('update', _('Update')),
        ('delete', _('Delete')),
        ('assign', _('Assign')),
        ('status_change', _('Status Change')),
        ('login', _('Login')),
        ('permission_change', _('Permission Change')),
        ('other', _('Other')),
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
    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('under_review', _('Under Review')),
        ('completed', _('Completed')),
    ]
    TYPE_CHOICES = [
        ('missed_pickup', _('Missed Pickup')),
        ('driver_behavior', _('Driver Behavior')),
        ('illegal_dumping', _('Illegal Dumping')),
        ('overflowing_bin', _('Overflowing Bin')),
        ('app_issue', _('App Issue')),
        ('other', _('Other')),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    complaint_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='other')
    subject = models.CharField(max_length=255, blank=True)
    description = models.TextField()
    photo = models.ImageField(
        upload_to='complaint_photos/',
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp']),
            validate_image_file,
        ],
        help_text='Accepted formats: JPG, JPEG, PNG, GIF, WebP (Max 5MB)'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    admin_response = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['complaint_type']),
        ]

    def save(self, *args, **kwargs):
        # Auto-fill subject from complaint_type if not explicitly provided,
        # so the admin dashboard's "subject" column always has something readable.
        if not self.subject:
            self.subject = self.get_complaint_type_display()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Complaint #{self.id} - {self.subject}"


class PushSubscription(models.Model):
    """A browser Web-Push (VAPID) subscription, registered by a logged-in
    citizen so status updates and notifications can be pushed even when the
    site/tab is closed. Endpoints/keys are opaque to Push Services by design."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_subscriptions',
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'push_subscriptions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"Push subscription for {self.user.username} ({self.endpoint[:60]}...)"