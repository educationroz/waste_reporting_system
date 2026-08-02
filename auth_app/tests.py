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

    def test_register_endpoint_ignores_submitted_role(self):
        """Public registration must never hand out a privileged role.

        Anyone can POST to /auth/register/, so honouring a submitted
        role='driver' would let a stranger promote themselves into the driver
        workforce (and onto pickup assignments) with no admin approval. The
        serializer forces role='user'; this locks that behaviour down.
        Real drivers are created by an admin instead.
        """
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

        created = User.objects.get(username='driver_reg_test')
        self.assertEqual(created.role, 'user')
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

        # No driver account, and therefore no driver profile, was created.
        self.assertEqual(User.objects.filter(role='driver').count(), 0)
        self.assertEqual(Driver.objects.count(), 0)

    def test_admin_created_driver_gets_profile(self):
        """The supported path for creating a driver: an admin makes the user."""
        driver_user = User.objects.create_user(
            username='admin_made_driver',
            email='admin_made_driver@example.com',
            password='StrongPass123!',
            role='driver',
        )

        self.assertEqual(User.objects.filter(role='driver').count(), 1)
        self.assertTrue(Driver.objects.filter(user=driver_user).exists())
