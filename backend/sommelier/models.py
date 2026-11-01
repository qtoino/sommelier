import secrets
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from sqlmodel import Field, SQLModel

Category = Literal[
    "correctness",
    "edge-case",
    "security",
    "performance",
    "readability",
    "api-design",
    "sql-and-schema",
]
Difficulty = Literal["easy", "medium", "hard"]
SourceType = Literal["mined", "synthetic"]
Status = Literal["active", "rejected", "flagged"]
Verification = Literal["verified", "unverifiable", "failed"]
Choice = Literal["left", "right", "depends"]
Confidence = Literal["low", "medium", "high"]
Side = Literal["good", "bad"]

CATEGORIES: tuple[str, ...] = get_args(Category)


def new_id() -> str:
    # Random, URL-safe, non-sequential so ids leak nothing about order or source.
    return secrets.token_urlsafe(8)


def now() -> datetime:
    return datetime.now(UTC)


class Item(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    language: str = "python"
    category: str = Field(index=True)
    difficulty: str = "medium"
    kind: str = "pairwise"
    prompt: str
    context_code: str | None = None
    version_good: str
    version_bad: str
    is_tradeoff: bool = False
    explanation: str
    tell: str
    source_type: str = Field(index=True)
    # mined
    repo: str | None = None
    commit_sha: str | None = None
    commit_url: str | None = None
    license_spdx: str | None = None
    original_path: str | None = None
    commit_message: str | None = None
    linked_issue_url: str | None = None
    # synthetic
    generator_model: str | None = None
    verification_status: str | None = None
    test_code: str | None = None

    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Attempt(SQLModel, table=True):
    # Created when an item is served (choice is NULL until answered), so the server
    # remembers which side was on the left without trusting the client.
    id: int | None = Field(default=None, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    shown_left: str  # Side
    choice: str | None = None  # Choice
    confidence: str | None = None
    reason_text: str | None = None
    is_correct: bool | None = None
    time_to_answer_ms: int | None = None
    created_at: datetime = Field(default_factory=now)
    answered_at: datetime | None = None


class ItemFlag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: str = Field(foreign_key="item.id", index=True)
    note: str
    created_at: datetime = Field(default_factory=now)


_ALLOWED: dict[str, tuple[str, ...]] = {
    "category": CATEGORIES,
    "difficulty": get_args(Difficulty),
    "source_type": get_args(SourceType),
    "status": get_args(Status),
    "kind": ("pairwise",),
}
_REQUIRED = ("prompt", "version_good", "version_bad", "explanation", "tell", "language")


def validate_item(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw item dict (from JSONL or the pipeline). Raises ValueError."""
    for key in _REQUIRED:
        if not str(data.get(key) or "").strip():
            raise ValueError(f"missing {key}")
    for key, allowed in _ALLOWED.items():
        if key in data and data[key] not in allowed:
            raise ValueError(f"bad {key}: {data[key]!r}")
    if "source_type" not in data:
        raise ValueError("missing source_type")
    if data["version_good"].strip() == data["version_bad"].strip():
        raise ValueError("versions are identical")
    if data["source_type"] == "mined":
        for key in ("repo", "commit_sha", "commit_url", "license_spdx"):
            if not data.get(key):
                raise ValueError(f"mined item missing {key}")
    if data.get("verification_status") not in (None, *get_args(Verification)):
        raise ValueError(f"bad verification_status: {data['verification_status']!r}")
    return data


def line_count(code: str) -> int:
    return len([ln for ln in code.strip().splitlines() if ln.strip()])
