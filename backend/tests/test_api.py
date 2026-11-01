from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from sommelier.app import grade
from sommelier.io import import_items
from sommelier.models import Item

SERVED_KEYS = {"attempt_id", "item_id", "language", "prompt", "context_code", "left", "right"}


def one_item(session: Session, **overrides: object) -> Item:
    data: dict[str, Any] = {
        "id": "x1",
        "category": "correctness",
        "source_type": "synthetic",
        "language": "python",
        "prompt": "p",
        "version_good": "def f():\n    return 1\n",
        "version_bad": "def f():\n    return 2\n",
        "explanation": "e",
        "tell": "t",
        **overrides,
    }
    import_items(session, [data])
    item = session.get(Item, data["id"])
    assert item
    return item


def answer(client: TestClient, choice: str, **params: Any) -> dict[str, Any]:
    served = client.get("/api/items/next", params=params).json()
    resp = client.post(
        "/api/attempts",
        json={"attempt_id": served["attempt_id"], "choice": choice, "confidence": "high"},
    )
    assert resp.status_code == 200
    return {**served, **resp.json()}


def test_grade_rules() -> None:
    assert grade("good", "left", False)
    assert grade("bad", "right", False)
    assert not grade("good", "right", False)
    assert not grade("good", "depends", False)
    assert grade("good", "depends", True)
    assert not grade("good", "left", True)


def test_next_leaks_nothing_and_randomizes(client: TestClient, seeded: Session) -> None:
    item = seeded.get(Item, "seed-hmac-compare")
    assert item
    lefts = set()
    for _ in range(40):
        served = client.get("/api/items/next", params={"category": "security"}).json()
        assert set(served) == SERVED_KEYS
        if served["item_id"] == item.id:
            assert {served["left"], served["right"]} == {item.version_good, item.version_bad}
            lefts.add(served["left"] == item.version_good)
        blob = str(served)
        for secret in ("explanation", "tell", "version_good", "commit_message", "is_tradeoff"):
            assert secret not in blob
    assert lefts == {True, False}


def test_server_side_grading_matches_placement(client: TestClient, session: Session) -> None:
    item = one_item(session)
    for _ in range(10):
        result = answer(client, "left")
        assert result["is_correct"] == (result["left"] == item.version_good)


def test_tradeoff_only_depends_is_right(client: TestClient, session: Session) -> None:
    one_item(session, is_tradeoff=True)
    assert answer(client, "depends")["is_correct"]
    assert not answer(client, "left")["is_correct"]
    assert not answer(client, "right")["is_correct"]


def test_double_submit_rejected(client: TestClient, session: Session) -> None:
    one_item(session)
    served = client.get("/api/items/next").json()
    body = {"attempt_id": served["attempt_id"], "choice": "left", "confidence": "low"}
    assert client.post("/api/attempts", json=body).status_code == 200
    assert client.post("/api/attempts", json=body).status_code == 409


def test_reveal_requires_answer(client: TestClient, session: Session) -> None:
    item = one_item(session)
    served = client.get("/api/items/next").json()
    assert client.get(f"/api/items/{item.id}/reveal").status_code == 403
    client.post(
        "/api/attempts",
        json={"attempt_id": served["attempt_id"], "choice": "right", "confidence": "low"},
    )
    data = client.get(f"/api/items/{item.id}/reveal").json()
    assert data["item"]["explanation"] == "e"
    assert data["good_side"] == ("left" if served["left"] == item.version_good else "right")


def test_flag_removes_from_rotation(client: TestClient, session: Session) -> None:
    item = one_item(session)
    resp = client.post(f"/api/items/{item.id}/flag", json={"note": "ambiguous"})
    assert resp.status_code == 200
    assert client.get("/api/items/next").status_code == 404


def test_unseen_first_then_review(client: TestClient, session: Session) -> None:
    one_item(session, id="a", is_tradeoff=True)
    one_item(session, id="b", is_tradeoff=True)
    first = answer(client, "left")  # wrong: tradeoff
    second = answer(client, "depends")  # right
    assert {first["item_id"], second["item_id"]} == {"a", "b"}
    for _ in range(5):
        served = client.get("/api/items/next", params={"review": True}).json()
        assert served["item_id"] == first["item_id"]


def test_stats(client: TestClient, session: Session) -> None:
    one_item(session, version_good="def f():\n    x = 1\n    return x\n")  # good is longer
    answer(client, "depends")
    stats = client.get("/api/stats").json()
    assert stats["overall"] == {"n": 1, "correct": 0}
    assert stats["by_confidence"]["high"] == {"n": 1, "correct": 0}
    assert stats["hedge_rate"] == 1.0
    assert stats["longer_baseline"] == 1.0
    assert stats["review_count"] == 1
    assert stats["inventory"] == {"correctness": 1}
