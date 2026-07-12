import json

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

    def test_register_endpoint_can_create_driver_user(self):
        payload = {
            'username': 'driver_reg_test',
            'email': 'driver_reg_test@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'role': 'driver',
            'phone': '1234567890',
            'address': 'Pokhara',
        }

        response = self.client.post(
            '/auth/register/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(User.objects.filter(role='driver').count(), 1)
        self.assertEqual(Driver.objects.count(), 1)
