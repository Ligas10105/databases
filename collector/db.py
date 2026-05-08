"""SQLite connection and write helpers for the collector."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and foreign keys."""
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_city_id(conn: sqlite3.Connection, city_name: str, country: str) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM cities WHERE name = ? AND country = ?",
        (city_name, country),
    ).fetchone()
    return row["id"] if row else None


def insert_measurement(conn: sqlite3.Connection, city_id: int, data: dict) -> bool:
    """Insert one measurement row. Returns True if inserted, False if duplicate."""
    placeholders = ", ".join("?" for _ in MEASUREMENT_COLUMNS)
    columns = ", ".join(MEASUREMENT_COLUMNS)
    values = tuple(data.get(col) for col in MEASUREMENT_COLUMNS)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO measurements (city_id, {columns}) VALUES (?, {placeholders})",
        (city_id, *values),
    )
    return cur.rowcount > 0


def log_collection_run(
    conn: sqlite3.Connection,
    cities_ok: int,
    cities_failed: int,
    source_used: str,
    notes: str = "",
) -> None:
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO collection_log (run_at, cities_ok, cities_failed, source_used, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_at, cities_ok, cities_failed, source_used, notes),
    )
