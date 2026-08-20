from django.test import TestCase
from django.contrib.auth import get_user_model
from api_app.models import AdminLog

User = get_user_model()


class AdminLogsViewTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_tester',
            password='Password123!',
            role='admin',
            is_staff=True,
            is_superadmin=True,
        )
        self.client.force_login(self.admin)
        for i in range(120):
            AdminLog.objects.create(
                admin_user=self.admin,
                action='create',
                content_type='Checkpoint',
                object_description=f'Log {i}',
            )

    def test_admin_logs_view_loads_and_paginates(self):
        response = self.client.get('/management/activity-logs/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_paginated'])
        self.assertIn('elided_page_range', response.context)

    def test_admin_logs_view_out_of_range_page_clamps_to_last(self):
        response = self.client.get('/management/activity-logs/?page=999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, response.context['paginator'].num_pages)

