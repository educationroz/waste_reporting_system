from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from .views import _create_notification
from .models import Notification, WasteRequest

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


class CheckpointPublicAccessTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='cpadmin',
            password='StrongPass123!',
            role='admin',
            is_staff=True,
            is_superuser=True,
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin_user)

    def test_anonymous_can_list_checkpoints_after_admin_creates_one(self):
        payload = {
            'name': 'Test Checkpoint',
            'description': 'Public test checkpoint',
            'latitude': 28.2096,
            'longitude': 83.9856,
            'is_active': True,
        }

        create_resp = self.admin_client.post('/api/checkpoints/', payload, format='json')
        self.assertIn(create_resp.status_code, (200, 201), create_resp.content)

        anon = APIClient()
        list_resp = anon.get('/api/checkpoints/')
        self.assertEqual(list_resp.status_code, 200, list_resp.content)
        data = list_resp.json()
        items = data if isinstance(data, list) else data.get('results', data)
        names = [i.get('name') for i in items]
        self.assertIn('Test Checkpoint', names)


class NotificationDedupeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='notifyuser',
            password='StrongPass123!',
            role='user',
        )

    def test_create_duplicate_notification_is_skipped(self):
        title = 'Hello'
        message = 'Duplicate test'
        n1 = _create_notification(self.user, title, message)
        # Immediate second call should be skipped by dedupe window (30s)
        n2 = _create_notification(self.user, title, message)

        qs = Notification.objects.filter(user=self.user, title=title, message=message)
        self.assertEqual(qs.count(), 1)
        self.assertIsNotNone(n1)
        self.assertIsNone(n2)


class WasteRequestLocationGroupingTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='requestadmin',
            password='StrongPass123!',
            role='admin',
            is_staff=True,
            is_superuser=True,
        )
        self.user_one = User.objects.create_user(
            username='reporter1',
            password='StrongPass123!',
            role='user',
        )
        self.user_two = User.objects.create_user(
            username='reporter2',
            password='StrongPass123!',
            role='user',
        )
        self.client = APIClient()

    def _payload(self):
        return {
            'waste_type': 'general',
            'pickup_address': 'Same Location Road 1',
            'scheduled_date': '2026-07-23T10:00:00Z',
            'description': 'Test pickup',
            'latitude': '28.209600',
            'longitude': '83.985600',
        }

    def test_same_location_requests_are_registered_and_completed_together(self):
        self.client.force_authenticate(user=self.user_one)
        first_response = self.client.post('/api/waste-requests/', self._payload(), format='json')
        self.assertEqual(first_response.status_code, 201, first_response.content)

        self.client.force_authenticate(user=self.user_two)
        second_response = self.client.post('/api/waste-requests/', self._payload(), format='json')
        self.assertEqual(second_response.status_code, 201, second_response.content)
        self.assertEqual(WasteRequest.objects.count(), 2)

        request_obj = WasteRequest.objects.order_by('id').first()
        self.assertIsNotNone(request_obj)

        self.client.force_authenticate(user=self.admin_user)
        complete_response = self.client.patch(
            f'/api/waste-requests/{request_obj.id}/update_status/',
            {'status': 'completed'},
            format='json',
        )
        self.assertEqual(complete_response.status_code, 200, complete_response.content)

        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, 'completed')
        self.assertIsNotNone(request_obj.completed_at)

        sibling_request = WasteRequest.objects.exclude(id=request_obj.id).get()
        sibling_request.refresh_from_db()
        self.assertEqual(sibling_request.status, 'completed')
        self.assertIsNotNone(sibling_request.completed_at)

        notifications = Notification.objects.filter(title='Report Completed')
        self.assertEqual(notifications.count(), 2)
        self.assertSetEqual(set(notifications.values_list('user_id', flat=True)), {self.user_one.id, self.user_two.id})

    def test_assign_driver_applies_to_same_location_siblings(self):
        driver_user = User.objects.create_user(
            username='route-driver',
            password='StrongPass123!',
            role='driver',
        )
        driver = driver_user.driver_profile

        first_request = WasteRequest.objects.create(
            user=self.user_one,
            waste_type='general',
            status='pending',
            description='Test pickup',
            pickup_address='Same Location Road 2',
            latitude='28.209600',
            longitude='83.985600',
            scheduled_date='2026-07-23T10:00:00Z',
        )
        second_request = WasteRequest.objects.create(
            user=self.user_two,
            waste_type='general',
            status='pending',
            description='Test pickup',
            pickup_address='Same Location Road 2 nearby',
            latitude='28.209628',
            longitude='83.985598',
            scheduled_date='2026-07-23T11:00:00Z',
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(
            f'/api/waste-requests/{first_request.id}/assign_driver/',
            {'driver_id': driver.id},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)

        first_request.refresh_from_db()
        second_request.refresh_from_db()
        self.assertEqual(first_request.status, 'assigned')
        self.assertEqual(second_request.status, 'assigned')
        self.assertEqual(first_request.driver_id, driver.id)
        self.assertEqual(second_request.driver_id, driver.id)
