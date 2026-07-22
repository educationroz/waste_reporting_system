from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api_app', '0014_checkpoint_wasterequest_dropoff_checkpoint'),
    ]

    operations = [
        migrations.AddField(
            model_name='wasterequest',
            name='submitting_users',
            field=models.ManyToManyField(blank=True, related_name='shared_waste_requests', to=settings.AUTH_USER_MODEL),
        ),
    ]