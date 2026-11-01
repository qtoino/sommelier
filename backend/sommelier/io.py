import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from sommelier.models import Item, now, validate_item

_SKIP_ON_IMPORT = {"created_at", "updated_at"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def import_items(session: Session, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """Upsert by id (rows without an id get a fresh one). Returns (created, updated)."""
    created = updated = 0
    for row in rows:
        data = validate_item({k: v for k, v in row.items() if k not in _SKIP_ON_IMPORT})
        existing = session.get(Item, data["id"]) if data.get("id") else None
        if existing:
            for key, value in data.items():
                setattr(existing, key, value)
            existing.updated_at = now()
            session.add(existing)
            updated += 1
        else:
            session.add(Item(**data))
            created += 1
    session.commit()
    return created, updated


def _default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value))


def export_items(session: Session, path: Path, status: str | None = None) -> int:
    query = select(Item).order_by(Item.id)
    if status:
        query = query.where(Item.status == status)
    items = session.exec(query).all()
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item.model_dump(), default=_default, ensure_ascii=False) + "\n")
    return len(items)
