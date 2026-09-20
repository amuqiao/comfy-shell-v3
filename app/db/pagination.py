from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from app.core.exceptions import AppError

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    next_cursor: str | None
    limit: int


def encode_cursor(*, created_at: datetime, item_id: str) -> str:
    payload = {"created_at": created_at.isoformat(), "id": item_id}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        item_id = str(payload["id"])
    except Exception as exc:
        raise AppError("REQUEST_INVALID", details={"cursor": "invalid"}) from exc
    return created_at, item_id

