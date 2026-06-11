"""Tests for collector.db using in-memory SQLite."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import db
from scripts.init_db import SCHEMA_SQL


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA_SQL)
    c.execute(
        "INSERT INTO cities (name, country, lat, lon) VALUES (?, ?, ?, ?)",
        ("Warsaw", "PL", 52.23, 21.01),
    )
    c.execute(
        "INSERT INTO cities (name, country, lat, lon) VALUES (?, ?, ?, ?)",
        ("Berlin", "DE", 52.52, 13.40),
    )
    c.commit()
    yield c
    c.close()


@pytest.fixture
def sample_measurement():
    return {
        "timestamp": "2024-01-15T12:00:00Z",
        "temp_c": 5.2,
        "feels_like_c": 2.1,
        "temp_min_c": 3.0,
        "temp_max_c": 7.5,
        "humidity_pct": 78,
        "pressure_hpa": 1013,
        "wind_speed_ms": 4.5,
        "wind_deg": 270,
        "clouds_pct": 40,
        "weather_main": "Clouds",
        "weather_desc": "scattered clouds",
        "source": "owm",
    }


def test_get_city_id_existing(conn):
    assert db.get_city_id(conn, "Warsaw", "PL") == 1
    assert db.get_city_id(conn, "Berlin", "DE") == 2


def test_get_city_id_missing(conn):
    assert db.get_city_id(conn, "Nowhere", "XX") is None


def test_insert_measurement_inserts_row(conn, sample_measurement):
    inserted = db.insert_measurement(conn, 1, sample_measurement)
    assert inserted is True

    row = conn.execute("SELECT * FROM measurements WHERE city_id = 1").fetchone()
    assert row is not None
    assert row["temp_c"] == 5.2
    assert row["weather_main"] == "Clouds"
    assert row["source"] == "owm"


def test_insert_measurement_skips_duplicate(conn, sample_measurement):
    first = db.insert_measurement(conn, 1, sample_measurement)
    second = db.insert_measurement(conn, 1, sample_measurement)
    assert first is True
    assert second is False

    count = conn.execute("SELECT COUNT(*) FROM measurements WHERE city_id = 1").fetchone()[0]
    assert count == 1


def test_insert_measurement_different_timestamps(conn, sample_measurement):
    db.insert_measurement(conn, 1, sample_measurement)
    second = dict(sample_measurement, timestamp="2024-01-15T12:30:00Z", temp_c=6.0)
    db.insert_measurement(conn, 1, second)

    rows = conn.execute(
        "SELECT timestamp FROM measurements WHERE city_id = 1 ORDER BY timestamp"
    ).fetchall()
    assert len(rows) == 2


def test_load_latest_per_city_filtered(tmp_path, sample_measurement):
    # data_loader otwiera bazę w trybie read-only (URI file:...?mode=ro),
    # więc zamiast :memory: tworzymy plikową bazę tymczasową.
    from dashboard.data_loader import load_latest_per_city_filtered

    db_path = tmp_path / "test.db"
    c = sqlite3.connect(db_path)
    c.executescript(SCHEMA_SQL)
    c.execute("INSERT INTO cities (name, country, lat, lon) VALUES ('Warsaw','PL',52.23,21.01)")
    c.execute("INSERT INTO cities (name, country, lat, lon) VALUES ('Berlin','DE',52.52,13.40)")
    # 2 pomiary per miasto — drugi nowszy
    for city_id, ts, temp in [
        (1, "2024-01-15T10:00:00Z", 1.0),
        (1, "2024-01-15T12:00:00Z", 5.2),
        (2, "2024-01-15T10:00:00Z", 2.0),
        (2, "2024-01-15T12:00:00Z", 7.0),
    ]:
        db.insert_measurement(c, city_id, dict(sample_measurement, timestamp=ts, temp_c=temp))
    c.commit()
    c.close()

    # filtr: tylko Warszawa, pełny zakres dat → 1 wiersz, najnowszy pomiar
    df = load_latest_per_city_filtered(db_path, {
        "start": "2024-01-15T00:00:00Z",
        "end": "2024-01-15T23:59:59Z",
        "city_ids": [1],
    })
    assert len(df) == 1
    assert df.iloc[0]["city"] == "Warsaw"
    assert df.iloc[0]["temp_c"] == 5.2

    # filtr: zakres dat obcinający nowszy pomiar → zwraca starszy per miasto
    df = load_latest_per_city_filtered(db_path, {
        "start": "2024-01-15T00:00:00Z",
        "end": "2024-01-15T11:00:00Z",
    })
    assert len(df) == 2
    assert sorted(df["temp_c"]) == [1.0, 2.0]

    # zakres bez danych → pusty DataFrame, brak wyjątku
    df = load_latest_per_city_filtered(db_path, {
        "start": "2030-01-01T00:00:00Z",
        "end": "2030-01-02T00:00:00Z",
    })
    assert df.empty


def test_log_collection_run(conn):
    db.log_collection_run(conn, cities_ok=18, cities_failed=2, source_used="owm:18", notes="failed: X,Y")
    row = conn.execute("SELECT * FROM collection_log").fetchone()
    assert row["cities_ok"] == 18
    assert row["cities_failed"] == 2
    assert row["source_used"] == "owm:18"
    assert "failed" in row["notes"]
    assert row["run_at"].endswith("Z")
