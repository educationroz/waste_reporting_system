<<<<<<< HEAD
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

=======
"""Tests for security response headers and page rendering.

``web_app/tests.py`` was an empty stub. These cover the CSP middleware added in
``waste_system/security.py`` plus a smoke test over every real route, which is
the cheapest way to catch a template that stops rendering.
"""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()


class CSPHeaderTests(TestCase):
    """CSP_MODE selects between compat / report / strict policies."""

    def _script_src(self, policy):
        return policy.split('script-src')[1].split(';')[0]

    @override_settings(CSP_MODE='compat')
    def test_compat_mode_keeps_unsafe_inline(self):
        response = self.client.get('/login/')
        policy = response.headers['Content-Security-Policy']

        self.assertIn("'unsafe-inline'", self._script_src(policy))
        self.assertNotIn('Content-Security-Policy-Report-Only', response.headers)

    @override_settings(CSP_MODE='report')
    def test_report_mode_enforces_permissive_and_reports_strict(self):
        """Report mode must not break anything: the ENFORCED policy stays
        permissive while the strict one is only reported on."""
        response = self.client.get('/login/')
        enforced = response.headers['Content-Security-Policy']
        reported = response.headers['Content-Security-Policy-Report-Only']

        self.assertIn("'unsafe-inline'", self._script_src(enforced))
        self.assertIn("'nonce-", self._script_src(reported))
        self.assertIn("'strict-dynamic'", self._script_src(reported))
        self.assertNotIn("'unsafe-inline'", self._script_src(reported))

    @override_settings(CSP_MODE='strict')
    def test_strict_mode_drops_unsafe_inline(self):
        response = self.client.get('/login/')
        policy = response.headers['Content-Security-Policy']

        self.assertIn("'nonce-", self._script_src(policy))
        self.assertIn("'strict-dynamic'", self._script_src(policy))
        self.assertNotIn("'unsafe-inline'", self._script_src(policy))

    @override_settings(CSP_MODE='strict')
    def test_nonce_differs_between_requests(self):
        """A reused nonce is no better than 'unsafe-inline'."""
        pattern = re.compile(r"'nonce-([^']+)'")
        first = pattern.search(
            self.client.get('/login/').headers['Content-Security-Policy']
        ).group(1)
        second = pattern.search(
            self.client.get('/login/').headers['Content-Security-Policy']
        ).group(1)

        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 20)

    @override_settings(CSP_MODE='strict')
    def test_rendered_inline_scripts_carry_the_header_nonce(self):
        """Every executable inline script must match the header, or strict
        mode silently breaks the page."""
        response = self.client.get('/login/')
        nonce = re.search(
            r"'nonce-([^']+)'", response.headers['Content-Security-Policy']
        ).group(1)
        html = response.content.decode()

        unnonced = [
            tag
            for tag in re.findall(r'<script([^>]*)>', html)
            if 'src=' not in tag
            and 'application/json' not in tag  # json_script: data, not code
            and f'nonce="{nonce}"' not in tag
        ]
        self.assertEqual(unnonced, [])

    def test_connect_src_allows_the_map_apis(self):
        """Nominatim/OSRM must stay allow-listed or address auto-fill and
        route planning break with a console CSP error."""
        policy = self.client.get('/login/').headers['Content-Security-Policy']
        connect_src = policy.split('connect-src')[1].split(';')[0]

        self.assertIn('nominatim.openstreetmap.org', connect_src)
        self.assertIn('router.project-osrm.org', connect_src)

    def test_connect_src_does_not_allow_arbitrary_hosts(self):
        policy = self.client.get('/login/').headers['Content-Security-Policy']
        self.assertNotIn('https://evil.example', policy)

    def test_hardening_headers_present(self):
        response = self.client.get('/login/')
        expected = {
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Cross-Origin-Opener-Policy': 'same-origin',
            'Cross-Origin-Resource-Policy': 'same-origin',
        }
        for header, value in expected.items():
            self.assertEqual(response.headers.get(header), value, header)

    def test_restrictive_directives_present(self):
        policy = self.client.get('/login/').headers['Content-Security-Policy']
        for directive in (
            "object-src 'none'",
            "form-action 'self'",
            "base-uri 'self'",
            "frame-ancestors 'self'",
        ):
            self.assertIn(directive, policy)

    @override_settings(CSP_MODE='report', CSP_REPORT_URI='https://csp.example/r')
    def test_report_uri_is_wired_when_configured(self):
        response = self.client.get('/login/')
        self.assertIn(
            'report-uri https://csp.example/r',
            response.headers['Content-Security-Policy'],
        )
        self.assertIn('csp-endpoint', response.headers.get('Reporting-Endpoints', ''))


class PageSmokeTests(TestCase):
    """Every real route renders for its intended role.

    A 500 here usually means a template broke — the class of regression this
    suite exists to catch.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='smokeadmin',
            password='pw',
            email='admin@example.com',
            role='admin',
            is_staff=True,
            is_superuser=True,
        )
        cls.driver = User.objects.create_user(
            username='smokedriver',
            password='pw',
            email='driver@example.com',
            role='driver',
        )
        cls.user = User.objects.create_user(
            username='smokeuser',
            password='pw',
            email='user@example.com',
            role='user',
        )

    def _assert_renders(self, username, paths):
        self.client.force_login(getattr(self, username))
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(
                    response.status_code, (200, 302), f'{path} -> {response.status_code}'
                )

    def test_public_pages_render(self):
        for path in ('/login/', '/register/', '/forgot-password/', '/jsi18n/'):
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, (200, 302))

    def test_admin_pages_render(self):
        self._assert_renders(
            'admin',
            [
                '/admin-dashboard/',
                '/management/requests/',
                '/management/complaints/',
                '/management/drivers/',
                '/management/vehicles/',
                '/management/schedules/',
                '/management/admin-users/',
                '/management/activity-logs/',
                '/management/settings/',
            ],
        )

    def test_driver_pages_render(self):
        self._assert_renders('driver', ['/driver-dashboard/', '/route-planning/'])

    def test_user_pages_render(self):
        self._assert_renders(
            'user',
            ['/', '/complaints/', '/recycle-bin/', '/profile/',
             '/my-requests/', '/notifications/'],
        )

    def test_pages_render_in_nepali(self):
        """The Nepali catalogue must actually apply, not just exist."""
        self.client.force_login(self.admin)
        response = self.client.get('/admin-dashboard/', HTTP_ACCEPT_LANGUAGE='ne')
        self.assertEqual(response.status_code, 200)

        body = response.content.decode()
        body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
        body = re.sub(r'<script.*?</script>', '', body, flags=re.S)
        body = re.sub(r'<style.*?</style>', '', body, flags=re.S)

        devanagari = re.findall(r'[\u0900-\u097F]+', body)
        self.assertGreater(len(devanagari), 50, 'dashboard did not render in Nepali')
>>>>>>> b89a62fbbe93201c3b4ab2be297aacb3c0f1ba4d
