"""
Tests for the /healthz readiness and /healthz/live liveness endpoints.

The important cases are the *unhappy* ones: a health check that only ever
returns 200 is indistinguishable from no health check at all, so most of what
follows breaks a dependency on purpose and asserts the endpoint reports 503.
"""

import json
from unittest import mock

from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from waste_system import health


class HealthzLiveTests(SimpleTestCase):
    """Liveness must stay dependency-free."""

    def test_returns_200_and_ok(self):
        response = self.client.get('/healthz/live')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'ok')
        self.assertIn('timestamp', payload)

    def test_is_reverseable_by_name(self):
        self.assertEqual(reverse('healthz-live'), '/healthz/live')

    def test_stays_up_when_every_dependency_is_broken(self):
        """
        The whole point of a separate liveness route: a Redis or database
        outage must not convince an orchestrator to restart the container.
        """
        boom = mock.Mock(side_effect=RuntimeError('everything is on fire'))
        with mock.patch.object(health, 'READINESS_CHECKS', (boom,)):
            response = self.client.get('/healthz/live')
        self.assertEqual(response.status_code, 200)
        boom.assert_not_called()

    def test_is_not_cached(self):
        response = self.client.get('/healthz/live')
        self.assertIn('no-store', response['Cache-Control'])

    def test_rejects_write_methods(self):
        self.assertEqual(self.client.post('/healthz/live').status_code, 405)
        self.assertEqual(self.client.delete('/healthz/live').status_code, 405)


class HealthzReadinessTests(TestCase):
    """Readiness probes the real dependencies."""

    def test_healthy_stack_returns_200(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(
            set(payload['checks']),
            {'database', 'cache', 'channels', 'redis'},
        )

    def test_is_reverseable_by_name(self):
        self.assertEqual(reverse('healthz'), '/healthz')

    def test_every_check_reports_a_duration(self):
        payload = self.client.get('/healthz').json()
        self.assertIsInstance(payload['duration_ms'], float)
        for name, result in payload['checks'].items():
            self.assertIn('duration_ms', result, msg=name)
            self.assertGreaterEqual(result['duration_ms'], 0, msg=name)

    def test_needs_no_authentication(self):
        """Probes arrive without a session; a 302 to /login would break them."""
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)

    def test_is_not_cached(self):
        response = self.client.get('/healthz')
        self.assertIn('no-store', response['Cache-Control'])

    def test_rejects_write_methods(self):
        self.assertEqual(self.client.post('/healthz').status_code, 405)

    def test_head_request_works(self):
        """LBs commonly probe with HEAD to avoid pulling a body."""
        self.assertEqual(self.client.head('/healthz').status_code, 200)

    # ── failure paths ────────────────────────────────────────────────────────

    def test_database_failure_returns_503(self):
        # Simulate the real thing — a cursor that refuses to open — rather
        # than stubbing check_database, which READINESS_CHECKS holds by
        # reference and so would not see the patch anyway.
        broken = mock.MagicMock()
        broken.cursor.side_effect = OperationalError('could not connect to server')
        with mock.patch.dict(health.connections, {'default': broken}, clear=False):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload['status'], 'failed')
        self.assertEqual(payload['checks']['database']['status'], 'failed')
        # The other checks still run, so an operator can see the blast radius.
        self.assertEqual(payload['checks']['cache']['status'], 'ok')

    def test_channel_layer_failure_returns_503(self):
        with mock.patch(
            'channels.layers.get_channel_layer',
            side_effect=RuntimeError('redis connection refused'),
        ):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['channels']['status'], 'failed')

    def test_missing_channel_layer_is_a_failure(self):
        # Detail forced ON here so the assertion can check the message text;
        # the production default for HEALTHCHECK_DETAIL is now False.
        with mock.patch('channels.layers.get_channel_layer', return_value=None), \
             mock.patch.object(health, 'HEALTHCHECK_DETAIL', True):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertIn('no channel layer', response.json()['checks']['channels']['error'])

    def test_cache_failure_returns_503(self):
        with mock.patch('waste_system.health.cache') as fake_cache:
            fake_cache.get.return_value = None  # write silently lost
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['cache']['status'], 'failed')

    def test_a_raising_probe_never_500s_the_endpoint(self):
        """
        A health endpoint that crashes tells the LB nothing. Any exception
        inside a probe must surface as a clean 503 body instead.
        """
        with mock.patch.object(
            health, 'connections',
            mock.MagicMock(__getitem__=mock.Mock(side_effect=Exception('catastrophe'))),
        ):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Content-Type'], 'application/json')
        json.loads(response.content)  # body is still valid JSON


class RedisProbeTests(TestCase):
    """Redis is optional, so 'not configured' must not read as 'broken'."""

    @override_settings(USE_REDIS=False)
    def test_skipped_when_redis_is_disabled(self):
        result = health.check_redis()
        self.assertEqual(result['status'], 'skipped')

    @override_settings(USE_REDIS=False)
    def test_skipped_does_not_fail_the_endpoint(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['checks']['redis']['status'], 'skipped')

    @override_settings(
        USE_REDIS=True, REDIS_HOST='127.0.0.1', REDIS_PORT=6379, REDIS_PASSWORD='',
    )
    def test_ping_success_when_redis_is_enabled(self):
        client = mock.Mock()
        client.ping.return_value = True
        with mock.patch.dict('sys.modules', {'redis': mock.Mock(Redis=mock.Mock(return_value=client))}):
            result = health.check_redis()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['host'], '127.0.0.1:6379')
        client.close.assert_called_once()

    @override_settings(
        USE_REDIS=True, REDIS_HOST='127.0.0.1', REDIS_PORT=6379, REDIS_PASSWORD='',
    )
    def test_retries_are_disabled_so_the_probe_fails_fast(self):
        """
        Regression: redis-py 5+ retries a refused connect three times with
        backoff, which made an unreachable Redis take ~6s to report against a
        2s HEALTHCHECK_TIMEOUT — long enough for the LB to time out first and
        lose the diagnosis.
        """
        # Patch only Redis, not the whole package: check_redis imports
        # redis.backoff/redis.retry, and stubbing sys.modules['redis'] would
        # make those imports fail into the ImportError fallback and silently
        # skip the very kwargs under test.
        with mock.patch('redis.Redis') as fake_redis:
            health.check_redis()
        kwargs = fake_redis.call_args.kwargs
        self.assertIn('retry', kwargs)
        self.assertEqual(kwargs['retry']._retries, 0)
        self.assertEqual(kwargs['retry_on_error'], [])
        self.assertEqual(kwargs['socket_connect_timeout'], health.HEALTHCHECK_TIMEOUT)

    @override_settings(
        USE_REDIS=True, REDIS_HOST='127.0.0.1', REDIS_PORT=6379, REDIS_PASSWORD='',
    )
    def test_unreachable_redis_fails_the_endpoint(self):
        redis_module = mock.Mock()
        redis_module.Redis.side_effect = OSError('connection refused')
        with mock.patch.dict('sys.modules', {'redis': redis_module}):
            response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['redis']['status'], 'failed')


class ErrorDetailTests(SimpleTestCase):
    """HEALTHCHECK_DETAIL=False must keep exception text out of the body."""

    def test_detail_on_includes_the_message(self):
        with mock.patch.object(health, 'HEALTHCHECK_DETAIL', True):
            detail = health._error_detail(ValueError('secret dsn leaked'))
        self.assertEqual(detail, 'ValueError: secret dsn leaked')

    def test_detail_off_reports_only_the_type(self):
        with mock.patch.object(health, 'HEALTHCHECK_DETAIL', False):
            detail = health._error_detail(ValueError('secret dsn leaked'))
        self.assertEqual(detail, 'ValueError')

    def test_message_is_collapsed_and_truncated(self):
        with mock.patch.object(health, 'HEALTHCHECK_DETAIL', True):
            detail = health._error_detail(ValueError('a\n  b' + 'x' * 500))
        self.assertNotIn('\n', detail)
        self.assertLessEqual(len(detail), 220)


class SslRedirectExemptionTests(TestCase):
    """
    SECURE_SSL_REDIRECT is on in production. Without the exemption a plain
    HTTP probe gets a 301, which every LB scores as unhealthy.
    """

    @override_settings(
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r'^healthz$', r'^healthz/live$'],
    )
    def test_probes_are_not_redirected_to_https(self):
        for url in ('/healthz', '/healthz/live'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    @override_settings(
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r'^healthz$', r'^healthz/live$'],
    )
    def test_other_urls_are_still_redirected(self):
        """The exemption must be narrow — it is not a blanket opt-out."""
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response['Location'].startswith('https://'))
