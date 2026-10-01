from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):

    ROLE_CHOICES = [
        ('admin', _('Admin')),
        ('driver', _('Driver')),
        ('user', _('Regular User')),
    ]
 
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')

    # Override AbstractUser.email: stored lowercased by save(), unique, and
    # nullable ('' is normalized to NULL so two accounts can't collide on the
    # empty string). Login stays username-based; email is used for verification
    # and password reset lookups (email__iexact => unambiguous now).
    email = models.EmailField(
        _('email address'),
        blank=True,
        null=True,
        unique=True,
        help_text='Stored lowercased; unique across all users.',
    )

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

    def save(self, *args, **kwargs):
        # Email normalization lives here (not just in the register serializer)
        # so every creation path — register, Google login, admin-created
        # accounts, shell scripts — stores lowercase, NULL-for-blank emails.
        # Combined with unique=True this makes 'X@Example.com' and
        # 'x@example.com' the same account.
        if self.email:
            self.email = self.email.strip().lower()
        else:
            self.email = None
        # `manage.py createsuperuser` (README setup step) only sets
        # is_superuser/is_staff — the role field keeps its 'user' default, and
        # every management page gates on role=='admin', so the superuser was
        # silently redirected away from ALL admin pages. Keep the two in sync:
        # a Django superuser is always an admin of this app.
        if self.is_superuser:
            if self.role != 'admin':
                self.role = 'admin'
            # Also grant app-level superadmin (admin-account management,
            # backup/restore) — but only when the account is FIRST created:
            # an existing superadmin can still be revoked via the
            # admin-users UI (that path saves with is_superuser still True,
            # and re-forcing the flag on every save would make revoking
            # impossible).
            if self._state.adding and not self.is_superadmin:
                self.is_superadmin = True
        super().save(*args, **kwargs)
 
    @property
    def is_admin(self):
        return self.role == 'admin'
 
    @property
    def is_driver(self):
        return self.role == 'driver'