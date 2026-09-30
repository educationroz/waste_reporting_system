import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

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
            logger.error('[RESEND] RESEND_API_KEY not configured')
            return 0

        sent = 0
        for message in email_messages:
            try:
                if self._send_message(message):
                    sent += 1
            except Exception:
                logger.exception('[RESEND] Failed to send email')
                if not self.fail_silently:
                    raise
        return sent

    def _build_payload(self, message):
        to = message.to
        if isinstance(to, str):
            to = [to]

        payload = {
            'from': message.from_email or settings.DEFAULT_FROM_EMAIL,
            'to': list(to),
            'subject': message.subject,
        }

        # Body: html if the message is html or has an html alternative
        if getattr(message, 'content_subtype', 'plain') == 'html':
            payload['html'] = message.body
        else:
            payload['text'] = message.body

        for content, mimetype in getattr(message, 'alternatives', []) or []:
            if mimetype == 'text/html':
                payload['html'] = content
                break

        if getattr(message, 'cc', None):
            payload['cc'] = list(message.cc)
        if getattr(message, 'bcc', None):
            payload['bcc'] = list(message.bcc)
        if getattr(message, 'reply_to', None):
            payload['reply_to'] = list(message.reply_to)

        return payload

    def _send_message(self, message):
        payload = self._build_payload(message)
        data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(
            self.api_url,
            data=data,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
                # Without this, Cloudflare in front of Resend can return 403 (code 1010)
                'User-Agent': 'SafhaSahar/1.0 (Django; +https://safhasahar.xyz)',
                'Accept': 'application/json',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read().decode('utf-8')
                logger.info(
                    '[RESEND] Email sent to %s (subject: %s) response: %s',
                    payload['to'], message.subject, body,
                )
                return True
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode('utf-8')
            except Exception:
                err_body = ''
            raise RuntimeError(f'Resend HTTP error {e.code}: {err_body}')
        except urllib.error.URLError as e:
            raise RuntimeError(f'Resend network error: {e.reason}')