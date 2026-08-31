"""
waste_system/logging_config.py

Structured logging helpers for the project.

- JsonFormatter: machine-readable single-line JSON per record (timestamp,
  level, logger, message, plus optional request/exception context) — the
  format most log-aggregation pipelines expect from a container/stdout.
- ExceptionsOnlyFilter: keeps only records carrying an exception (used for
  the optional file handler so routine WARNING noise doesn't grow an
  unbounded file).

Settings wire these up in waste_system/settings.py LOGGING.
"""

import json
import logging


class JsonFormatter(logging.Formatter):
    """Emit each record as one JSON object on one line."""

    def format(self, record):
        payload = {
            'ts': self.formatTime(record, datefmt='%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }
        if getattr(record, 'request', None) is not None:
            payload['request'] = str(record.request)
        if getattr(record, 'status_code', None) is not None:
            payload['status_code'] = record.status_code
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        if record.stack_info:
            payload['stack'] = self.formatStack(record.stack_info)

        # Surface extra={...} keys so domain context added by callers flows
        # through structured logs untouched. LogRecord's built-in attributes
        # are skipped; context fields are set explicitly above.
        builtins = set(vars(logging.makeLogRecord({})).keys()) | {'message', 'asctime'}
        for key, value in record.__dict__.items():
            if key in builtins or key in payload:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = str(value)

        return json.dumps(payload, ensure_ascii=False, default=str)


class ExceptionsOnlyFilter(logging.Filter):
    """Keep only records with an attached exception (exc_info set)."""

    def filter(self, record):
        return bool(record.exc_info)