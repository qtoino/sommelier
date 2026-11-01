from sqlmodel import SQLModel

import sommelier.models  # noqa: F401  (registers tables)
from alembic import context
from sommelier.db import make_engine

target_metadata = SQLModel.metadata

with make_engine().connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
