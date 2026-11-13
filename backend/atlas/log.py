"""Logs estruturados em JSON (uma linha por evento)."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "ctx", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def get_logger(name: str) -> logging.Logger:
    root = logging.getLogger("atlas")
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
        root.setLevel(logging.INFO)
        root.propagate = False
    return logging.getLogger(f"atlas.{name}")


def ctx(**kw) -> dict:
    """Uso: log.info("mensagem", extra=ctx(linhas=10))."""
    return {"ctx": kw}
