from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'phone', 'is_verified', 'is_active', 'date_joined')
    list_filter = ('role', 'is_verified', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'phone')
    ordering = ('-date_joined',)

    fieldsets = UserAdmin.fieldsets + (
        ('Waste System Fields', {
            'fields': ('role', 'phone', 'address', 'profile_picture', 'is_verified'),
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Waste System Fields', {
            'fields': ('email', 'role', 'phone', 'address'),
        }),
    )