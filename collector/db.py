"""Warstwa zapisu przez ORM (SQLAlchemy) — używana przez backfill i init_db.

Cały dostęp do bazy idzie przez modele z `collector.models` i sesję ORM.
Tworzenie schematu (CREATE TABLE) realizuje `Base.metadata.create_all`
w init_db; tutaj dostarczamy silnik, fabrykę sesji oraz funkcje zapisu.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from collector.models import City, CollectionLog, Measurement


# Kolumny pomiaru wypełniane z dicta zwracanego przez parser backfillu.
MEASUREMENT_COLUMNS = (
    "timestamp",
    "temp_c",
    "feels_like_c",
    "temp_min_c",
    "temp_max_c",
    "humidity_pct",
    "pressure_hpa",
    "wind_speed_ms",
    "wind_deg",
    "clouds_pct",
    "weather_main",
    "weather_desc",
    "source",
)


def get_engine(db_path: str | Path, *, echo: bool = False) -> Engine:
    """Silnik SQLAlchemy do zapisu (SQLite z WAL i włączonymi kluczami obcymi)."""
    engine = create_engine(f"sqlite:///{db_path}", echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.close()

    return engine


def get_sessionmaker(db_path: str | Path) -> sessionmaker:
    """Fabryka sesji ORM związana z silnikiem dla danej ścieżki bazy."""
    return sessionmaker(bind=get_engine(db_path), future=True)


def get_session(db_path: str | Path) -> Session:
    """Pojedyncza sesja ORM (wygodny skrót dla skryptów)."""
    return Session(get_engine(db_path), future=True)


def get_city_id(session: Session, city_name: str, country: str) -> Optional[int]:
    """Zwraca id miasta po nazwie i kraju albo None, gdy go nie ma."""
    return session.execute(
        select(City.id).where(City.name == city_name, City.country == country)
    ).scalar_one_or_none()


def insert_measurement(session: Session, city_id: int, data: dict) -> bool:
    """Wstawia jeden pomiar. Zwraca True, jeśli dodano; False przy duplikacie.

    Odpowiednik dawnego INSERT OR IGNORE: próbujemy dodać rekord w obrębie
    zagnieżdżonej transakcji (SAVEPOINT). Gdy UNIQUE(city_id, timestamp)
    odrzuci duplikat (IntegrityError), wycofujemy TYLKO ten savepoint —
    wcześniej dodane w sesji pomiary zostają nienaruszone.
    """
    values = {col: data.get(col) for col in MEASUREMENT_COLUMNS}
    measurement = Measurement(city_id=city_id, **values)
    try:
        with session.begin_nested():
            session.add(measurement)
        return True
    except IntegrityError:
        return False


def log_collection_run(
    session: Session,
    cities_ok: int,
    cities_failed: int,
    source_used: str,
    notes: str = "",
) -> None:
    """Dopisuje wpis do collection_log (commit po stronie wywołującego)."""
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session.add(
        CollectionLog(
            run_at=run_at,
            cities_ok=cities_ok,
            cities_failed=cities_failed,
            source_used=source_used,
            notes=notes,
        )
    )
    session.flush()
