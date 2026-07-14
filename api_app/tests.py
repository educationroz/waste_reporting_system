from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


class BackupRestoreAPITest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='backupadmin',
            password='StrongPass123!',
            role='admin',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin_user)

    def test_backup_endpoint_creates_file_and_restore_accepts_it(self):
        backup_response = self.client.post('/api/database-backups/backup/')
        self.assertEqual(backup_response.status_code, 200, backup_response.content)

        backup_data = backup_response.json()
        self.assertIn('file_name', backup_data)
        self.assertTrue(backup_data['file_name'].endswith('.json'))

        file_name = backup_data['file_name']
        file_path = backup_data['file_path']
        with open(file_path, 'rb') as f:
            uploaded = SimpleUploadedFile(file_name, f.read(), content_type='application/json')

        restore_response = self.client.post(
            '/api/database-backups/restore/',
            {'backup_file': uploaded},
            format='multipart',
        )

        self.assertEqual(restore_response.status_code, 200, restore_response.content)
        self.assertIn('restored', restore_response.json()['message'].lower())


class DriverDeletionAPITest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='driveradmin',
            password='StrongPass123!',
            role='admin',
            is_staff=True,
            is_superuser=True,
        )
        self.driver_user = User.objects.create_user(
            username='driver1',
            email='driver1@example.com',
            password='StrongPass123!',
            role='driver',
        )
        self.driver = self.driver_user.driver_profile
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

    def test_destroy_driver_removes_linked_user_and_profile(self):
        response = self.client.delete(f'/api/drivers/{self.driver.id}/')

        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(User.objects.filter(id=self.driver_user.id).exists())
        self.assertFalse(self.driver.__class__.objects.filter(id=self.driver.id).exists())
