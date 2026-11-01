from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from sommelier.io import export_items, import_items, read_jsonl
from sommelier.models import CATEGORIES, Item, validate_item

from .conftest import SEED


def test_seed_is_valid_and_varied(seeded: Session) -> None:
    items = seeded.exec(select(Item)).all()
    assert len(items) >= 10
    assert any(i.is_tradeoff for i in items)
    assert {i.category for i in items} == set(CATEGORIES)


def test_round_trip(seeded: Session, session: Session, tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    n = export_items(seeded, out)
    rows = read_jsonl(out)
    assert len(rows) == n
    assert import_items(session, rows) == (0, n)  # same ids update, no duplicates
    assert {r["id"] for r in rows} == {r["id"] for r in read_jsonl(SEED)}


@pytest.mark.parametrize(
    "patch",
    [
        {"category": "vibes"},
        {"version_good": "same", "version_bad": "same"},
        {"source_type": "mined"},  # missing attribution
        {"tell": ""},
    ],
)
def test_validation_rejects(patch: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_item({**read_jsonl(SEED)[0], **patch})
