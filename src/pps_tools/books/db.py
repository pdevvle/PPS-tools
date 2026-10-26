"""Database engine, session and column types.

SQLite by default (one file per company); any SQLAlchemy URL works via
BOOKS_DATABASE_URL. Money columns are BIGINT cents; quantities and
rates use :class:`DecimalString`, which keeps Decimals exact on SQLite.
"""

from __future__ import annotations

import functools
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import JSON, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class DecimalString(TypeDecorator):
    """A Decimal stored as text so SQLite never rounds it through a float."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return format(value, "f")

    def process_result_value(self, value: Any, dialect) -> Optional[Decimal]:
        if value is None or value == "":
            return None
        return Decimal(value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_engine(url: str, echo: bool = False) -> Engine:
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        in_memory = url in ("sqlite://", "sqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def _sqlite_connect(dbapi_conn, _record):  # pragma: no cover - trivial
            # Let SQLAlchemy own BEGIN so SAVEPOINTs work (see the pysqlite
            # notes in the SQLAlchemy docs); every save runs in one.
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if not in_memory:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):  # pragma: no cover - trivial
            conn.exec_driver_sql("BEGIN")
    return engine


def atomic(fn):
    """Run a service function in a SAVEPOINT: on error nothing it did sticks,
    and the caller's session is still usable."""

    @functools.wraps(fn)
    def wrapper(s: Session, *args, **kwargs):
        with s.begin_nested():
            return fn(s, *args, **kwargs)

    return wrapper


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)


def create_schema(engine: Engine) -> None:
    from pps_tools.books import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker) -> Iterator[Session]:
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def dumps(value: Any) -> str:
    """JSON for audit snapshots: Decimals and dates as strings."""
    return json.dumps(value, default=_json_default, sort_keys=True)


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return format(o, "f")
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")
