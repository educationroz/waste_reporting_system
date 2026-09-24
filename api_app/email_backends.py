"""
Resend HTTP API email backend for Django.
Bypasses SMTP entirely — works on Railway/Render/Fly where SMTP ports are blocked.

Requires:
- Resend account with verified domain
- RESEND_API_KEY in .env
- DEFAULT_FROM_EMAIL must use your verified domain (e.g., noreply@safhasahar.com)
"""
import json
import logging
from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """
    Django email backend using Resend's HTTP API.
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, 'RESEND_API_KEY', None)
        self.api_url = 'https://api.resend.com/emails'

    def send_messages(self, email_messages):
        if not self.api_key:
            if not self.fail_silently:
                raise ValueError('RESEND_API_KEY not configured in settings')
            return 0

        sent = 0
        for message in email_messages:
            try:
                if self._send_message(message):
                    sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception('[RESEND] Failed to send email')
        return sent

    def _send_message(self, message):
        import urllib.request
        import urllib.error

        # Build payload
        from_email = message.from_email or settings.DEFAULT_FROM_EMAIL
        to = message.to
        if isinstance(to, str):
            to = [to]

        payload = {
            'from': from_email,
            'to': to,
            'subject': message.subject,
        }

        # Prefer HTML if available
        if hasattr(message, 'alternatives') and message.alternatives:
            for content, mimetype in message.alternatives:
                if mimetype == 'text/html':
                    payload['html'] = content
                    break
        else:
            payload['text'] = message.body

        # Optional: reply-to
        if hasattr(message, 'reply_to') and message.reply_to:
            payload['reply_to'] = message.reply_to

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.api_url,
            data=data,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status >= 400:
                    body = response.read().decode('utf-8')
                    raise RuntimeError(f'Resend API error {response.status}: {body}')
                logger.info('[RESEND] Email sent to %s (subject: %s)', to, message.subject)
                return True
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8') if e.fp else ''
            raise RuntimeError(f'Resend HTTP error {e.code}: {body}')
        except urllib.error.URLError as e:
            raise RuntimeError(f'Resend network error: {e.reason}')