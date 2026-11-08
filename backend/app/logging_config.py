"""Structured JSON logging to stdout with request correlation IDs.

Never pass passwords, session tokens, CSRF tokens, account numbers or other
customer data into log records.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}
_SENSITIVE_KEYS = {"password", "token", "session", "csrf", "cookie", "authorization", "account_number"}


class JsonFormatter(logging.Formatter):
    def __init__(self, instance_id: str) -> None:
        super().__init__()
        self.instance_id = instance_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "instance": self.instance_id,
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if any(s in key.lower() for s in _SENSITIVE_KEYS):
                value = "[redacted]"
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, instance_id: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(instance_id))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn's access log duplicates our own request log; keep its errors.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
