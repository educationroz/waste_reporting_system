from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):

    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('driver', 'Driver'),
        ('user', 'Regular User'),
    ]
 
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(
        upload_to='profile_pics/', blank=True, null=True
    )
    is_verified = models.BooleanField(default=False)
    is_superadmin = models.BooleanField(
        default=False,
        help_text='Superadmins can manage other admin accounts and restore the database. '
                   'Regular admins (operators) cannot.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        db_table = 'auth_users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
 
    def __str__(self):
        return f"{self.username} ({self.role})"
 
    @property
    def is_admin(self):
        return self.role == 'admin'
 
    @property
    def is_driver(self):
        return self.role == 'driver'