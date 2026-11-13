"""Ambiente do Alembic: usa a URL de banco definida em ATLAS_DATABASE_URL."""
from alembic import context

from atlas.db import engine
from atlas.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
