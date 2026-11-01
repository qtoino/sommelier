from collections import Counter
from pathlib import Path

import typer
from sqlmodel import Session, select

from sommelier.db import engine
from sommelier.io import export_items, import_items, read_jsonl
from sommelier.models import Item

app = typer.Typer(help="Sommelier content pipeline. Never runs in the web request path.")


@app.command("import")
def import_cmd(path: Path) -> None:
    """Load items from a JSONL file (upsert by id)."""
    with Session(engine) as session:
        created, updated = import_items(session, read_jsonl(path))
    typer.echo(f"created {created}, updated {updated}")


@app.command("export")
def export_cmd(path: Path, status: str | None = None) -> None:
    """Write items to a JSONL file."""
    with Session(engine) as session:
        typer.echo(f"exported {export_items(session, path, status)} items to {path}")


@app.command("stats")
def stats_cmd() -> None:
    """Item counts by category / source / status."""
    with Session(engine) as session:
        items = session.exec(select(Item)).all()
    typer.echo(f"total: {len(items)}")
    for field in ("status", "source_type", "category", "difficulty", "is_tradeoff"):
        counts = Counter(str(getattr(i, field)) for i in items)
        typer.echo(f"{field}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    active = [i for i in items if i.status == "active"]
    by_cat = Counter((i.category, i.source_type) for i in active)
    typer.echo(
        "active by category/source: "
        + ", ".join(f"{c}/{s}={n}" for (c, s), n in sorted(by_cat.items()))
    )
