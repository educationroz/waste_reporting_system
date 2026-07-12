from django.contrib.auth import get_user_model
from django.test import TestCase

from api_app.models import Driver

User = get_user_model()


class DriverProfileSyncTest(TestCase):
    def test_driver_user_auto_creates_driver_profile(self):
        user = User.objects.create_user(
            username='Driver1',
            email='driver1@example.com',
            password='StrongPass123!',
            role='driver',
        )

        self.assertTrue(Driver.objects.filter(user=user).exists())
        driver = Driver.objects.get(user=user)
        self.assertEqual(driver.license_number, f'DRIVER-{user.id}')
