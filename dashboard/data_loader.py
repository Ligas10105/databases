"""Zapytania dashboardu — cały dostęp do bazy (read-only) przez ORM SQLAlchemy.

Dashboard czyta bazę w trybie read-only (URI file:...?mode=ro); jedynym
pisarzem jest backfill. Zapytania budujemy przez `select()` na modelach
z `collector.models` — wspólny zestaw warunków filtrujących (`_build_where`)
dzieli logikę między widokami, tak jak wcześniej dzielił klauzulę WHERE.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import Engine, create_engine, func, null, select
from sqlalchemy.orm import aliased

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collector.models import City, Measurement


# Mapowanie nazwy parametru z paska bocznego na kolumnę pomiaru.
# Wartości to nazwy kolumn DataFrame/atrybutów modelu (używane też przez widoki).
PARAM_COLUMNS = {
    "temperature": "temp_c",
    "feels_like": "feels_like_c",
    "humidity": "humidity_pct",
    "pressure": "pressure_hpa",
    "wind_speed": "wind_speed_ms",
    "clouds": "clouds_pct",
}


@lru_cache(maxsize=None)
def _read_engine_cached(abs_path: str) -> Engine:
    """Silnik read-only dla danej ścieżki (cache — jeden silnik na plik).

    Otwieramy bazę przez URI SQLite w trybie read-only (mode=ro): dashboard
    nigdy nie pisze. `uri=true` w adresie włącza tryb URI w sterowniku pysqlite.
    """
    return create_engine(
        f"sqlite:///file:{abs_path}?mode=ro&uri=true",
        future=True,
    )


def _read_engine(db_path: str | Path) -> Engine:
    # Ścieżka bezwzględna — URI 'file:/...' jest jednoznaczne (bez cwd).
    return _read_engine_cached(str(Path(db_path).resolve()))


def _param_column(parameter: str):
    """Atrybut modelu Measurement odpowiadający wybranemu parametrowi."""
    return getattr(Measurement, PARAM_COLUMNS.get(parameter, "temp_c"))


def list_cities(db_path: str | Path) -> pd.DataFrame:
    stmt = select(
        City.id, City.name, City.country, City.lat, City.lon
    ).order_by(City.name)
    with _read_engine(db_path).connect() as conn:
        return pd.read_sql_query(stmt, conn)


def list_weather_conditions(db_path: str | Path) -> list[str]:
    stmt = (
        select(Measurement.weather_main)
        .where(Measurement.weather_main.is_not(None))
        .distinct()
        .order_by(Measurement.weather_main)
    )
    with _read_engine(db_path).connect() as conn:
        return [r[0] for r in conn.execute(stmt)]


def _build_where(filters: dict) -> list:
    """Buduje listę warunków filtrujących (wyrażeń SQLAlchemy) z paska bocznego.

    Wspólne dla load_measurements i load_latest_per_city_filtered — dzięki temu
    wszystkie widoki filtrują identycznie. Warunki odnoszą się do modelu
    Measurement; do złożenia używa się `.where(*conds)`.
    """
    column = _param_column(filters.get("parameter", "temperature"))
    conds: list = []

    if filters.get("start"):
        conds.append(Measurement.timestamp >= filters["start"])
    if filters.get("end"):
        conds.append(Measurement.timestamp <= filters["end"])

    city_ids: Iterable[int] | None = filters.get("city_ids")
    if city_ids:
        city_ids = list(city_ids)
        if city_ids:
            conds.append(Measurement.city_id.in_(city_ids))

    if filters.get("value_min") is not None:
        conds.append(column >= filters["value_min"])
    if filters.get("value_max") is not None:
        conds.append(column <= filters["value_max"])

    conditions = filters.get("weather_conditions")
    if conditions:
        conditions = list(conditions)
        if conditions:
            conds.append(Measurement.weather_main.in_(conditions))

    return conds


def load_measurements(db_path: str | Path, filters: dict) -> pd.DataFrame:
    """Load measurements with optional filtering and aggregation.

    filters keys:
      - start (ISO str), end (ISO str)
      - city_ids: iterable[int]
      - parameter: one of PARAM_COLUMNS keys (used for value-range filter only)
      - value_min, value_max: floats
      - weather_conditions: iterable[str]
      - aggregation: 'raw' | 'hourly' | 'daily' | 'weekly'
    """
    aggregation = filters.get("aggregation", "raw")
    conds = _build_where(filters)

    if aggregation == "raw":
        stmt = (
            select(
                City.id.label("city_id"),
                City.name.label("city"),
                City.country,
                City.lat,
                City.lon,
                Measurement.timestamp,
                Measurement.temp_c,
                Measurement.feels_like_c,
                Measurement.humidity_pct,
                Measurement.pressure_hpa,
                Measurement.wind_speed_ms,
                Measurement.clouds_pct,
                Measurement.weather_main,
                Measurement.weather_desc,
                Measurement.source,
            )
            .join(City, City.id == Measurement.city_id)
            .where(*conds)
            .order_by(Measurement.timestamp.asc())
        )
    else:
        bucket_fmt = {
            "hourly": "%Y-%m-%dT%H:00:00Z",
            "daily": "%Y-%m-%dT00:00:00Z",
            "weekly": "%Y-W%W",
        }[aggregation]
        bucket = func.strftime(bucket_fmt, Measurement.timestamp).label("timestamp")
        stmt = (
            select(
                City.id.label("city_id"),
                City.name.label("city"),
                City.country,
                City.lat,
                City.lon,
                bucket,
                func.avg(Measurement.temp_c).label("temp_c"),
                func.avg(Measurement.feels_like_c).label("feels_like_c"),
                func.avg(Measurement.humidity_pct).label("humidity_pct"),
                func.avg(Measurement.pressure_hpa).label("pressure_hpa"),
                func.avg(Measurement.wind_speed_ms).label("wind_speed_ms"),
                func.avg(Measurement.clouds_pct).label("clouds_pct"),
                null().label("weather_main"),
                null().label("weather_desc"),
                null().label("source"),
            )
            .join(City, City.id == Measurement.city_id)
            .where(*conds)
            .group_by(City.id, func.strftime(bucket_fmt, Measurement.timestamp))
            .order_by(bucket.asc())
        )

    with _read_engine(db_path).connect() as conn:
        df = pd.read_sql_query(stmt, conn)

    if not df.empty and aggregation in ("raw", "hourly", "daily"):
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def load_latest_per_city(db_path: str | Path) -> pd.DataFrame:
    """Najnowszy pomiar per miasto (bez filtrów); miasta bez danych jako NULL."""
    # Skalarny podzapyt: id najnowszego pomiaru dla danego miasta.
    latest_id = (
        select(Measurement.id)
        .where(Measurement.city_id == City.id)
        .order_by(Measurement.timestamp.desc())
        .limit(1)
        .scalar_subquery()
    )
    m = aliased(Measurement)
    stmt = (
        select(
            City.id.label("city_id"),
            City.name.label("city"),
            City.country,
            City.lat,
            City.lon,
            m.timestamp,
            m.temp_c,
            m.feels_like_c,
            m.humidity_pct,
            m.pressure_hpa,
            m.wind_speed_ms,
            m.clouds_pct,
            m.weather_main,
            m.weather_desc,
        )
        .select_from(City)
        .join(m, m.id == latest_id, isouter=True)
        .order_by(City.name)
    )
    with _read_engine(db_path).connect() as conn:
        df = pd.read_sql_query(stmt, conn)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def load_latest_per_city_filtered(db_path: str | Path, filters: dict) -> pd.DataFrame:
    """Najnowszy pomiar per miasto, ale TYLKO spośród rekordów spełniających filtry.

    Te same warunki co load_measurements (wspólny _build_where). Podzapytanie
    wybiera MAX(timestamp) per city_id z przefiltrowanego zbioru; dzięki
    UNIQUE(city_id, timestamp) para (city_id, max_ts) wskazuje dokładnie jeden
    rekord, więc filtrów nie trzeba powtarzać w zapytaniu zewnętrznym.
    Zwraca te same kolumny co load_latest_per_city.
    """
    conds = _build_where(filters)
    latest = (
        select(
            Measurement.city_id.label("cid"),
            func.max(Measurement.timestamp).label("max_ts"),
        )
        .where(*conds)
        .group_by(Measurement.city_id)
        .subquery()
    )
    stmt = (
        select(
            City.id.label("city_id"),
            City.name.label("city"),
            City.country,
            City.lat,
            City.lon,
            Measurement.timestamp,
            Measurement.temp_c,
            Measurement.feels_like_c,
            Measurement.humidity_pct,
            Measurement.pressure_hpa,
            Measurement.wind_speed_ms,
            Measurement.clouds_pct,
            Measurement.weather_main,
            Measurement.weather_desc,
        )
        .join(City, City.id == Measurement.city_id)
        .join(
            latest,
            (latest.c.cid == Measurement.city_id)
            & (latest.c.max_ts == Measurement.timestamp),
        )
        .order_by(City.name)
    )
    with _read_engine(db_path).connect() as conn:
        df = pd.read_sql_query(stmt, conn)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def get_value_range(db_path: str | Path, parameter: str) -> tuple[float, float]:
    column = _param_column(parameter)
    stmt = select(func.min(column), func.max(column)).where(column.is_not(None))
    with _read_engine(db_path).connect() as conn:
        row = conn.execute(stmt).one()
    if not row or row[0] is None:
        return (0.0, 0.0)
    return (float(row[0]), float(row[1]))
