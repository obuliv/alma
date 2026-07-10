from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_db_url = make_url(settings.database_url)
if _db_url.get_backend_name() == "sqlite" and _db_url.database not in (None, ":memory:"):
    # SQLite won't create missing parent directories on connect.
    Path(_db_url.database).parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False: background tasks (session_scope) use the engine off
# the request thread, which pysqlite blocks by default.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional session for work outside the request cycle (background
    tasks, the automation worker, CLIs). Commits on success, rolls back on
    error, always closes."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
