from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    future=True,
    # timeout: espera até 60 s por um bloqueio de escrita (cargas simultâneas) antes de falhar
    connect_args={"check_same_thread": False, "timeout": 60} if _is_sqlite else {},
    pool_size=settings.db_pool_size,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):  # pragma: no cover - configuração do driver
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA cache_size=-{settings.sqlite_cache_mb * 1000}")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope():
    s: Session = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session():
    """Dependência FastAPI."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
