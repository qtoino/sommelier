import os
from collections.abc import Iterator

from dotenv import load_dotenv
from sqlalchemy import Engine
from sqlmodel import Session, create_engine

load_dotenv()


def db_url() -> str:
    return (
        os.environ.get("SOMMELIER_DB_URL")
        or f"sqlite:///{os.environ.get('SOMMELIER_DB', 'sommelier.db')}"
    )


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or db_url(), connect_args={"check_same_thread": False})


engine = make_engine()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
