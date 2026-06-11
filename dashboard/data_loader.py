"""SQL queries for the dashboard. All DB access lives here."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd


PARAM_COLUMNS = {
    "temperature": "temp_c",
    "feels_like": "feels_like_c",
    "humidity": "humidity_pct",
    "pressure": "pressure_hpa",
    "wind_speed": "wind_speed_ms",
    "clouds": "clouds_pct",
}


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def list_cities(db_path: str | Path) -> pd.DataFrame:
    with _connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT id, name, country, lat, lon FROM cities ORDER BY name",
            conn,
        )


def list_weather_conditions(db_path: str | Path) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT weather_main FROM measurements "
            "WHERE weather_main IS NOT NULL ORDER BY weather_main"
        ).fetchall()
    return [r[0] for r in rows]


def _build_where(filters: dict) -> tuple[str, list]:
    """Buduje klauzulę WHERE i listę parametrów z filtrów paska bocznego.

    Wspólne dla load_measurements i load_latest_per_city_filtered —
    dzięki temu wszystkie widoki filtrują identycznie. Warunki odnoszą się
    do tabeli measurements pod aliasem `m`.

    Zwraca: (where_sql, params), gdzie where_sql to "WHERE ..." albo "".
    """
    column = PARAM_COLUMNS.get(filters.get("parameter", "temperature"), "temp_c")

    where: list[str] = []
    params: list = []

    if filters.get("start"):
        where.append("m.timestamp >= ?")
        params.append(filters["start"])
    if filters.get("end"):
        where.append("m.timestamp <= ?")
        params.append(filters["end"])

    city_ids: Iterable[int] | None = filters.get("city_ids")
    if city_ids:
        city_ids = list(city_ids)
        if city_ids:
            where.append(f"m.city_id IN ({','.join('?' for _ in city_ids)})")
            params.extend(city_ids)

    if filters.get("value_min") is not None:
        where.append(f"m.{column} >= ?")
        params.append(filters["value_min"])
    if filters.get("value_max") is not None:
        where.append(f"m.{column} <= ?")
        params.append(filters["value_max"])

    conditions = filters.get("weather_conditions")
    if conditions:
        conditions = list(conditions)
        if conditions:
            where.append(f"m.weather_main IN ({','.join('?' for _ in conditions)})")
            params.extend(conditions)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


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
    where_sql, params = _build_where(filters)

    if aggregation == "raw":
        query = f"""
            SELECT
                c.id   AS city_id,
                c.name AS city,
                c.country,
                c.lat,
                c.lon,
                m.timestamp,
                m.temp_c,
                m.feels_like_c,
                m.humidity_pct,
                m.pressure_hpa,
                m.wind_speed_ms,
                m.clouds_pct,
                m.weather_main,
                m.weather_desc,
                m.source
            FROM measurements m
            JOIN cities c ON c.id = m.city_id
            {where_sql}
            ORDER BY m.timestamp ASC
        """
    else:
        bucket_fmt = {
            "hourly": "%Y-%m-%dT%H:00:00Z",
            "daily": "%Y-%m-%dT00:00:00Z",
            "weekly": "%Y-W%W",
        }[aggregation]
        query = f"""
            SELECT
                c.id   AS city_id,
                c.name AS city,
                c.country,
                c.lat,
                c.lon,
                strftime(?, m.timestamp) AS timestamp,
                AVG(m.temp_c)         AS temp_c,
                AVG(m.feels_like_c)   AS feels_like_c,
                AVG(m.humidity_pct)   AS humidity_pct,
                AVG(m.pressure_hpa)   AS pressure_hpa,
                AVG(m.wind_speed_ms)  AS wind_speed_ms,
                AVG(m.clouds_pct)     AS clouds_pct,
                NULL AS weather_main,
                NULL AS weather_desc,
                NULL AS source
            FROM measurements m
            JOIN cities c ON c.id = m.city_id
            {where_sql}
            GROUP BY c.id, strftime(?, m.timestamp)
            ORDER BY timestamp ASC
        """
        params = [bucket_fmt, *params, bucket_fmt]

    with _connect(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if not df.empty and aggregation in ("raw", "hourly", "daily"):
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def load_latest_per_city(db_path: str | Path) -> pd.DataFrame:
    query = """
        SELECT
            c.id AS city_id, c.name AS city, c.country, c.lat, c.lon,
            m.timestamp, m.temp_c, m.feels_like_c, m.humidity_pct,
            m.pressure_hpa, m.wind_speed_ms, m.clouds_pct,
            m.weather_main, m.weather_desc
        FROM cities c
        LEFT JOIN measurements m ON m.id = (
            SELECT id FROM measurements
            WHERE city_id = c.id
            ORDER BY timestamp DESC
            LIMIT 1
        )
        ORDER BY c.name
    """
    with _connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def load_latest_per_city_filtered(db_path: str | Path, filters: dict) -> pd.DataFrame:
    """Najnowszy pomiar per miasto, ale TYLKO spośród rekordów spełniających filtry.

    Te same warunki WHERE co load_measurements (wspólny _build_where).
    Podzapytanie wybiera MAX(timestamp) per city_id z przefiltrowanego zbioru;
    dzięki UNIQUE(city_id, timestamp) para (city_id, max_ts) wskazuje dokładnie
    jeden rekord, więc filtrów nie trzeba powtarzać w zapytaniu zewnętrznym.
    Zwraca te same kolumny co load_latest_per_city.
    """
    where_sql, params = _build_where(filters)
    query = f"""
        SELECT
            c.id AS city_id, c.name AS city, c.country, c.lat, c.lon,
            m.timestamp, m.temp_c, m.feels_like_c, m.humidity_pct,
            m.pressure_hpa, m.wind_speed_ms, m.clouds_pct,
            m.weather_main, m.weather_desc
        FROM measurements m
        JOIN cities c ON c.id = m.city_id
        JOIN (
            SELECT m.city_id AS cid, MAX(m.timestamp) AS max_ts
            FROM measurements m
            {where_sql}
            GROUP BY m.city_id
        ) latest ON latest.cid = m.city_id AND latest.max_ts = m.timestamp
        ORDER BY c.name
    """
    with _connect(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def get_value_range(db_path: str | Path, parameter: str) -> tuple[float, float]:
    column = PARAM_COLUMNS.get(parameter, "temp_c")
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT MIN({column}), MAX({column}) FROM measurements WHERE {column} IS NOT NULL"
        ).fetchone()
    if not row or row[0] is None:
        return (0.0, 0.0)
    return (float(row[0]), float(row[1]))
