import random
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from sommelier.db import get_session
from sommelier.models import Attempt, Choice, Confidence, Item, ItemFlag, line_count, now

app = FastAPI(title="Sommelier")
SessionDep = Annotated[Session, Depends(get_session)]


def grade(shown_left: str, choice: str, is_tradeoff: bool) -> bool:
    """Tradeoff items are only right with 'depends'; 'depends' is wrong everywhere else."""
    if is_tradeoff:
        return choice == "depends"
    good_side = "left" if shown_left == "good" else "right"
    return choice == good_side


def _answered(session: Session) -> list[tuple[Attempt, Item]]:
    rows = session.exec(
        select(Attempt, Item)
        .join(Item)
        .where(col(Attempt.choice).is_not(None))
        .order_by(col(Attempt.answered_at))
    ).all()
    return [(a, i) for a, i in rows]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class Served(BaseModel):
    """Everything the client may see before answering. No labels, no explanation."""

    attempt_id: int
    item_id: str
    language: str
    prompt: str
    context_code: str | None
    left: str
    right: str


@app.get("/api/items/next")
def next_item(
    session: SessionDep,
    category: str | None = None,
    source_type: str | None = None,
    difficulty: str | None = None,
    review: bool = False,
    exclude: str | None = None,
) -> Served:
    query = select(Item).where(Item.status == "active")
    if category:
        query = query.where(Item.category == category)
    if source_type:
        query = query.where(Item.source_type == source_type)
    if difficulty:
        query = query.where(Item.difficulty == difficulty)
    items = session.exec(query).all()

    last = {a.item_id: a for a, _ in _answered(session)}
    if review:
        pool = [i for i in items if i.id in last and not last[i.id].is_correct]
    else:
        pool = [i for i in items if i.id not in last] or list(items)
    if exclude and len(pool) > 1:
        pool = [i for i in pool if i.id != exclude]
    if not pool:
        raise HTTPException(404, "No items match these filters.")

    item = random.choice(pool)
    attempt = Attempt(item_id=item.id, shown_left=random.choice(("good", "bad")))
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    assert attempt.id is not None
    good_left = attempt.shown_left == "good"
    return Served(
        attempt_id=attempt.id,
        item_id=item.id,
        language=item.language,
        prompt=item.prompt,
        context_code=item.context_code,
        left=item.version_good if good_left else item.version_bad,
        right=item.version_bad if good_left else item.version_good,
    )


class AttemptIn(BaseModel):
    attempt_id: int
    choice: Choice
    confidence: Confidence
    reason_text: str | None = Field(default=None, max_length=2000)


@app.post("/api/attempts")
def submit_attempt(body: AttemptIn, session: SessionDep) -> dict[str, Any]:
    attempt = session.get(Attempt, body.attempt_id)
    if attempt is None:
        raise HTTPException(404, "Unknown attempt.")
    if attempt.choice is not None:
        raise HTTPException(409, "Already answered.")
    item = session.get(Item, attempt.item_id)
    assert item is not None
    answered_at = now()
    attempt.choice = body.choice
    attempt.confidence = body.confidence
    attempt.reason_text = (body.reason_text or "").strip() or None
    attempt.is_correct = grade(attempt.shown_left, body.choice, item.is_tradeoff)
    attempt.answered_at = answered_at
    created = attempt.created_at.replace(tzinfo=attempt.created_at.tzinfo or UTC)
    attempt.time_to_answer_ms = int((answered_at - created).total_seconds() * 1000)
    session.add(attempt)
    session.commit()
    return {"item_id": item.id, "is_correct": attempt.is_correct}


@app.get("/api/items/{item_id}/reveal")
def reveal(item_id: str, session: SessionDep) -> dict[str, Any]:
    attempt = session.exec(
        select(Attempt)
        .where(Attempt.item_id == item_id, col(Attempt.choice).is_not(None))
        .order_by(col(Attempt.answered_at).desc())
    ).first()
    if attempt is None:
        raise HTTPException(403, "Answer the item before revealing it.")
    item = session.get(Item, item_id)
    assert item is not None
    return {
        "item": item.model_dump(),
        "good_side": "left" if attempt.shown_left == "good" else "right",
        "choice": attempt.choice,
        "confidence": attempt.confidence,
        "is_correct": attempt.is_correct,
    }


class FlagIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@app.post("/api/items/{item_id}/flag")
def flag(item_id: str, body: FlagIn, session: SessionDep) -> dict[str, str]:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Unknown item.")
    item.status = "flagged"
    item.updated_at = now()
    session.add(item)
    session.add(ItemFlag(item_id=item_id, note=body.note))
    session.commit()
    return {"status": "flagged"}


def _bucket() -> dict[str, int]:
    return {"n": 0, "correct": 0}


@app.get("/api/stats")
def stats(session: SessionDep) -> dict[str, Any]:
    groups: dict[str, dict[str, dict[str, int]]] = {
        "by_category": {},
        "by_confidence": {},
        "by_source": {},
        "by_difficulty": {},
    }
    overall = _bucket()
    hedges = 0
    longer_score = 0.0
    rows = _answered(session)
    for attempt, item in rows:
        keys = {
            "by_category": item.category,
            "by_confidence": attempt.confidence or "?",
            "by_source": item.source_type,
            "by_difficulty": item.difficulty,
        }
        for b in [overall, *(groups[g].setdefault(k, _bucket()) for g, k in keys.items())]:
            b["n"] += 1
            b["correct"] += bool(attempt.is_correct)
        hedges += attempt.choice == "depends"
        # Baseline: always pick the longer version (never says 'depends'; ties are a coin flip).
        if not item.is_tradeoff:
            good, bad = line_count(item.version_good), line_count(item.version_bad)
            longer_score += 1.0 if good > bad else 0.5 if good == bad else 0.0

    inventory: dict[str, int] = {}
    for category in session.exec(select(Item.category).where(Item.status == "active")).all():
        inventory[category] = inventory.get(category, 0) + 1

    recent = [
        {
            "item_id": item.id,
            "prompt": item.prompt,
            "category": item.category,
            "choice": attempt.choice,
            "confidence": attempt.confidence,
            "is_correct": attempt.is_correct,
            "answered_at": attempt.answered_at,
        }
        for attempt, item in reversed(rows[-20:])
    ]
    n = overall["n"]
    # Match review mode: only active items can be served, so flagged ones aren't counted.
    last = {item.id: (a, item) for a, item in rows}
    return {
        "overall": overall,
        **groups,
        "hedge_rate": hedges / n if n else 0.0,
        "longer_baseline": longer_score / n if n else 0.0,
        "review_count": sum(
            1 for a, item in last.values() if not a.is_correct and item.status == "active"
        ),
        "inventory": inventory,
        "recent": recent,
    }


_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
