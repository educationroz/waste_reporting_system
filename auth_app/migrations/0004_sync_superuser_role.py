# Data migration: `manage.py createsuperuser` (README setup step) only sets
# is_superuser/is_staff — it never touches role / is_superadmin, both of which
# default to 'user'/False. Every management page and the
# IsSuperAdminUser permission gate on those fields, so a superuser created
# that way was silently redirected away from ALL admin pages (404-ish lockout
# on fresh installs, including Railway deploys following the README).
#
# One-way sync only: is_superuser=True  =>  role='admin' + is_superadmin=True.
# Never the reverse — regular operator admins (role='admin', is_superuser=False)
# and revoked superadmins must be left untouched.

from django.db import migrations


def sync_superuser_flags(apps, schema_editor):
    User = apps.get_model('auth_app', 'User')
    User.objects.filter(is_superuser=True).exclude(role='admin').update(role='admin')
    User.objects.filter(is_superuser=True, is_superadmin=False).update(is_superadmin=True)


class Migration(migrations.Migration):

    dependencies = [
        ('auth_app', '0003_alter_user_email'),
    ]

    operations = [
        migrations.RunPython(
            sync_superuser_flags,
            migrations.RunPython.noop,  # reverse is a no-op: flags only widen access
        ),
    ]
