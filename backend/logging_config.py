"""
Centralised logging setup.

- `compass.app`     — general app events (startup, scheduler, misc).
- `compass.auth`    — login/logout/refresh/register outcomes.
- `compass.access`  — one line per HTTP request, emitted by the middleware.
- `compass.llm`     — DeepSeek / meal-generator calls.
- `compass.audit`   — admin actions (written to a separate file with long retention).

Every log record is decorated with `request_id`, `journey_id`, `ui_action`,
and `user_id` via a contextvar-backed filter so a single user action can be
traced across access logs, business events, and retries.

Never log: raw passwords, JWTs, refresh-token strings, full bodies of
auth-related requests. The middleware deliberately ignores query
strings and bodies for this reason.
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

# ── Context variables (populated by the request middleware) ───────────────────

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
journey_id_var: ContextVar[Optional[str]] = ContextVar("journey_id", default=None)
ui_action_var: ContextVar[Optional[str]] = ContextVar("ui_action", default=None)
user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)


class RequestContextFilter(logging.Filter):
    """Attach request-scoped contextvars onto every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        record.journey_id = journey_id_var.get() or record.request_id
        record.ui_action = ui_action_var.get() or "-"
        uid = user_id_var.get()
        record.user_id = uid if uid is not None else "-"
        return True


class JsonFormatter(logging.Formatter):
    """Compact JSON formatter. One record per line."""

    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "journey_id": getattr(record, "journey_id", "-"),
            "ui_action": getattr(record, "ui_action", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        # Anything passed via `extra={...}` that isn't a reserved attribute
        # gets merged into the JSON payload, so call sites can add fields
        # without hand-stringifying them.
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure() -> None:
    """Idempotent. Call once from main.py before the app starts serving."""
    log_dir = Path(os.getenv("LOG_DIR", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,

        "filters": {
            "context": {"()": RequestContextFilter},
        },

        "formatters": {
            "json": {"()": JsonFormatter},
            "console": {
                "format": "%(asctime)s %(levelname)-7s %(name)s [req=%(request_id)s jid=%(journey_id)s uid=%(user_id)s action=%(ui_action)s] :: %(message)s",
                "datefmt": "%H:%M:%S",
            },
        },

        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "console",
                "filters": ["context"],
            },
            "applog": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_dir / "app.log"),
                "when": "midnight",
                "backupCount": 14,
                "encoding": "utf-8",
                "formatter": "json",
                "filters": ["context"],
            },
            "auditlog": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_dir / "audit.log"),
                "when": "midnight",
                "backupCount": 90,
                "encoding": "utf-8",
                "formatter": "json",
                "filters": ["context"],
            },
        },

        "loggers": {
            "compass":       {"handlers": ["stdout", "applog"], "level": "INFO", "propagate": False},
            "compass.audit": {"handlers": ["stdout", "auditlog"], "level": "INFO", "propagate": False},
            # uvicorn's own access log is noisy and not request-id aware; we
            # emit our own via the middleware, so silence the default.
            "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False},
            "uvicorn.error":  {"handlers": ["stdout", "applog"], "level": "INFO", "propagate": False},
        },

        "root": {"handlers": ["stdout"], "level": "WARNING"},
    })
