"""
api_app/tasks.py

Background task runner for expensive, non-request-critical work.

The heaviest offender is the ML waste classifier: torch + torchvision load a
~2GB+ MobileNet and run CPU inference per photo. Running that synchronously
inside the upload request path blocks the web worker for the whole inference
window (the old behaviour — see the removed predict_waste call in
serializers.py), which makes citizen uploads feel frozen and lets one slow
photo stall every other request on that worker.

This module moves inference (and anything else slow) onto a dedicated thread
pool so the request thread returns immediately and the result is written back
to the database a moment later. No Redis/Celery/extra infra is required: the
executor is process-local, which is precisely the right scope here.

Design notes
------------
- ONE shared ThreadPoolExecutor per process, sized generously but bounded by
  ``ML_MAX_WORKERS`` (default: 2) rather than os.cpu_count() — the model is
  CPU-bound and oversized pools only thrash the L3 cache / torch threads.
  Tune via settings; 0 disables background execution (runs synchronously).
- Each task writes its own DB results. In Django every thread needs its own
  DB connection — Django handles this automatically because the connection is
  created lazily per-thread and closed when the thread ends. Long-lived pool
  threads keep one connection open each; that is acceptable and standard.
- torch allows the GIL during CPU compute, so separate uploads genuinely run
  in parallel instead of serializing.

Thread-safety of the model itself
---------------------------------
predict_waste() lazily builds a module-level singleton and does
torch.no_grad() inference on it. Concurrent inference on a single eval-mode
model is safe (no gradient state is mutated); the pool is provided mainly so
the brand-new task never blocks/freezes a request worker.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_executor = None
_email_executor = None


def _get_executor():
    """Lazily create the process-wide thread pool (safe to call from any thread)."""
    global _executor
    if _executor is None:
        max_workers = getattr(settings, 'ML_MAX_WORKERS', 2)
        if max_workers <= 0:
            return None
        _executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='ml-task',
        )
    return _executor


def shutdown_executor():
    """Gracefully stop the pools on app shutdown (see api_app/apps.py)."""
    global _executor, _email_executor
    for pool in (_executor, _email_executor):
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=False)
    _executor = None
    _email_executor = None


def submit(fn, *args, **kwargs):
    """
    Schedule ``fn`` on the background pool and return its Future.
    If background execution is disabled (ML_MAX_WORKERS=0) it runs
    synchronously and returns an already-finished Future.
    """
    executor = _get_executor()
    if executor is None:
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - we must set, never leave pending
            future.set_exception(exc)
        return future
    return executor.submit(fn, *args, **kwargs)


def run_ml_classification_async(waste_request_id, image_bytes):
    """
    Background task: classify a photo and write the result back to the
    WasteRequest row. Runs on the pool; never touches the caller's request.

    Args:
        waste_request_id: PK of the WasteRequest to update.
        image_bytes: raw bytes of the sanitized image (re-opened in this
            thread, so no shared file pointer races with the caller).

    Returns the ML result dict on success (also persisted), or None.
    """
    from django.db import close_old_connections

    from .models import WasteRequest

    close_old_connections()
    try:
        from ml_models.waste_classifier.inference import predict_waste
        try:
            from io import BytesIO
            result = predict_waste(BytesIO(image_bytes))
        except Exception:
            # Model file missing / corrupt model / bad image. Can't classify —
            # leave the request flagged for manual review so an admin decides.
            logger.exception(
                f'[ML] inference failed for request={waste_request_id}; flagging for manual review.'
            )
            result = None

        updated = WasteRequest.objects.filter(pk=waste_request_id).update(
            severity=(result['severity'] if result else None),
            ml_confidence=(result['confidence'] if result else 0.0),
            needs_manual_review=(not result or result['needs_manual_review'] or not result['is_waste']),
            updated_at=timezone.now(),
        )
        if not updated:
            logger.warning(f'[ML] request={waste_request_id} not found for classification update.')
            return result

        # Auto-assign driver for HIGH waste with confidence >= 80%
        if result and result.get('severity') == 'high' and result.get('confidence', 0) >= 80:
            try:
                from .views import WasteRequestViewSet
                waste_request = WasteRequest.objects.select_related('driver').get(pk=waste_request_id)
                # Only auto-assign if still pending and no driver
                if waste_request.status == 'pending' and waste_request.driver is None:
                    viewset = WasteRequestViewSet()
                    viewset._auto_assign_driver_for_request(waste_request)
            except Exception:
                logger.exception(f'[ML] auto-assign failed for request={waste_request_id}')

        return result
    finally:
        close_old_connections()


def _get_email_executor():
    """Lazily create a small pool for outgoing email so SMTP latency never
    blocks an HTTP request. Kept separate from the ML pool: mail is I/O-bound
    and must not compete for the CPU-inference threads."""
    global _email_executor
    if _email_executor is None:
        max_workers = getattr(settings, 'EMAIL_MAX_WORKERS', 2)
        if max_workers <= 0:
            return None
        _email_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='mail-task',
        )
    return _email_executor


def send_mail_async(subject, message, from_email, recipient_list, **kwargs):
    """
    Send an email on a background thread so the request returns immediately.

    Mirrors django.core.mail.send_mail's signature (extra kwargs such as
    fail_silently, html_message, auth_user/auth_password are forwarded
    verbatim). Deferred failures are logged, never raised into the request.

    When EMAIL_MAX_WORKERS=0 it falls back to a synchronous send (old
    behaviour), preserving a debugging escape hatch.
    """
    def _send():
        from django.core.mail import send_mail
        try:
            send_mail(subject, message, from_email, recipient_list, **kwargs)
        except Exception:
            logger.exception(
                '[MAIL] failed to send to %s (subject=%s)',
                recipient_list, subject,
            )

    executor = _get_email_executor()
    if executor is None:
        _send()
        return
    executor.submit(_send)
