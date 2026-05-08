"""Initialize SQLite database: create schema and insert cities from config.yaml."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = PROJECT_ROOT / "config.yaml"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    UNIQUE(name, country)
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL REFERENCES cities(id),
    timestamp TEXT NOT NULL,
    temp_c REAL,
    feels_like_c REAL,
    temp_min_c REAL,
    temp_max_c REAL,
    humidity_pct INTEGER,
    pressure_hpa INTEGER,
    wind_speed_ms REAL,
    wind_deg INTEGER,
    clouds_pct INTEGER,
    weather_main TEXT,
    weather_desc TEXT,
    source TEXT DEFAULT 'owm',
    UNIQUE(city_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_measurements_city_time
    ON measurements(city_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_measurements_time
    ON measurements(timestamp);

CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    cities_ok INTEGER,
    cities_failed INTEGER,
    source_used TEXT,
    notes TEXT
);
"""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_db(db_path: Path, cities: list[dict]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA_SQL)
        for city in cities:
            conn.execute(
                "INSERT OR IGNORE INTO cities (name, country, lat, lon) VALUES (?, ?, ?, ?)",
                (city["name"], city["country"], city["lat"], city["lon"]),
            )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
        print(f"DB initialized at {db_path}. Cities in DB: {count}")
    finally:
        conn.close()


def main() -> None:
    config = load_config()
    db_path = PROJECT_ROOT / config.get("database", {}).get("path", "data/weather.db")
    cities = config["collection"]["cities"]
    init_db(db_path, cities)


if __name__ == "__main__":
    main()
