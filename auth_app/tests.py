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


class BiometricAuthTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='bio_user',
            email='bio@example.com',
            password='StrongPass123!',
            role='user',
        )

    def test_biometric_token_registration_and_passwordless_login(self):
        self.client.force_login(self.user)
        reg_resp = self.client.post('/auth/biometric-register-token/')
        self.assertEqual(reg_resp.status_code, 200)
        token = reg_resp.json()['token']

        # Logout and perform biometric login
        self.client.logout()
        login_resp = self.client.post(
            '/auth/biometric-login/',
            data=json.dumps({'username': 'bio_user', 'token': token}),
            content_type='application/json'
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertEqual(login_resp.json()['user']['username'], 'bio_user')

    def test_biometric_login_with_invalid_token_fails(self):
        login_resp = self.client.post(
            '/auth/biometric-login/',
            data=json.dumps({'username': 'bio_user', 'token': 'tampered_token_xyz'}),
            content_type='application/json'
        )
        self.assertEqual(login_resp.status_code, 401)

    def test_export_user_data_download(self):
        self.client.force_login(self.user)
        resp = self.client.get('/auth/export-data/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/json', resp['Content-Type'])
        self.assertIn('attachment;', resp['Content-Disposition'])
        data = resp.json()
        self.assertEqual(data['account_info']['username'], 'bio_user')
        self.assertIn('waste_requests', data)
        self.assertIn('complaints', data)

    def test_settings_page_routes(self):
        self.client.force_login(self.user)
        for url in ['/profile/', '/settings/']:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Personal Settings')
