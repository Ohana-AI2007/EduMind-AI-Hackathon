from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import BASE_DIR, settings


class Base(DeclarativeBase):
    pass


def _resolve_url(url: str) -> str:
    prefix = "sqlite:///"
    if url.startswith(prefix) and ":memory:" not in url:
        p = Path(url[len(prefix):])
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return prefix + p.as_posix()
    return url


_url = _resolve_url(settings.database_url)
engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if _url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def init_db() -> None:
    from backend import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()