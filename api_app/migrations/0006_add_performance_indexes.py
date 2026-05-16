# Generated migration for adding performance indexes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_app', '0005_systemsettings_adminlog'),
    ]

    operations = [
        # Vehicle indexes
        migrations.AddIndex(
            model_name='vehicle',
            index=models.Index(fields=['status', '-created_at'], name='vehicles_status_created_at_idx'),
        ),
        migrations.AddIndex(
            model_name='vehicle',
            index=models.Index(fields=['vehicle_type', 'status'], name='vehicles_type_status_idx'),
        ),

        # Driver indexes
        migrations.AddIndex(
            model_name='driver',
            index=models.Index(fields=['is_available', 'vehicle'], name='drivers_available_vehicle_idx'),
        ),
        migrations.AddIndex(
            model_name='driver',
            index=models.Index(fields=['is_available', '-created_at'], name='drivers_available_created_idx'),
        ),

        # Bin indexes
        migrations.AddIndex(
            model_name='bin',
            index=models.Index(fields=['status', 'waste_type'], name='bins_status_type_idx'),
        ),
        migrations.AddIndex(
            model_name='bin',
            index=models.Index(fields=['status', '-created_at'], name='bins_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='bin',
            index=models.Index(fields=['waste_type'], name='bins_waste_type_idx'),
        ),

        # WasteRequest indexes
        migrations.AddIndex(
            model_name='wasterequest',
            index=models.Index(fields=['status', 'scheduled_date'], name='requests_status_scheduled_idx'),
        ),
        migrations.AddIndex(
            model_name='wasterequest',
            index=models.Index(fields=['user', 'status'], name='requests_user_status_idx'),
        ),
        migrations.AddIndex(
            model_name='wasterequest',
            index=models.Index(fields=['driver', 'status'], name='requests_driver_status_idx'),
        ),
        migrations.AddIndex(
            model_name='wasterequest',
            index=models.Index(fields=['status', '-created_at'], name='requests_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='wasterequest',
            index=models.Index(fields=['-created_at'], name='requests_created_idx'),
        ),

        # Route indexes
        migrations.AddIndex(
            model_name='route',
            index=models.Index(fields=['driver', 'status'], name='routes_driver_status_idx'),
        ),
        migrations.AddIndex(
            model_name='route',
            index=models.Index(fields=['vehicle', 'status'], name='routes_vehicle_status_idx'),
        ),
        migrations.AddIndex(
            model_name='route',
            index=models.Index(fields=['status', '-planned_date'], name='routes_status_planned_idx'),
        ),

        # Schedule indexes
        migrations.AddIndex(
            model_name='schedule',
            index=models.Index(fields=['driver', 'is_active'], name='schedules_driver_active_idx'),
        ),
        migrations.AddIndex(
            model_name='schedule',
            index=models.Index(fields=['vehicle', 'is_active'], name='schedules_vehicle_active_idx'),
        ),
        migrations.AddIndex(
            model_name='schedule',
            index=models.Index(fields=['is_active', 'zone_name'], name='schedules_active_zone_idx'),
        ),

        # Notification indexes
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', 'is_read'], name='notifs_user_read_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', '-created_at'], name='notifs_user_created_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['is_read', '-created_at'], name='notifs_read_created_idx'),
        ),

        # Update WasteRequest photo field to add FileExtensionValidator
        migrations.AlterField(
            model_name='wasterequest',
            name='photo',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='waste_photos/',
                validators=[__import__('django.core.validators', fromlist=['FileExtensionValidator']).FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp'])],
                help_text='Accepted formats: JPG, JPEG, PNG, GIF, WebP (Max 5MB)'
            ),
        ),
    ]
