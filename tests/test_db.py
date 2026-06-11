"""Testy collector.db przez ORM (SQLAlchemy) na bazie w pamięci."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import db
from collector.models import Base, City, CollectionLog, Measurement


@pytest.fixture
def session():
    # Baza w pamięci, schemat tworzony z modeli ORM (zamiast surowego SQL).
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        s.add(City(name="Warsaw", country="PL", lat=52.23, lon=21.01))
        s.add(City(name="Berlin", country="DE", lat=52.52, lon=13.40))
        s.commit()
        yield s


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


def test_get_city_id_existing(session):
    assert db.get_city_id(session, "Warsaw", "PL") == 1
    assert db.get_city_id(session, "Berlin", "DE") == 2


def test_get_city_id_missing(session):
    assert db.get_city_id(session, "Nowhere", "XX") is None


def test_insert_measurement_inserts_row(session, sample_measurement):
    inserted = db.insert_measurement(session, 1, sample_measurement)
    assert inserted is True

    row = session.execute(
        select(Measurement).where(Measurement.city_id == 1)
    ).scalar_one()
    assert row is not None
    assert row.temp_c == 5.2
    assert row.weather_main == "Clouds"
    assert row.source == "owm"


def test_insert_measurement_skips_duplicate(session, sample_measurement):
    first = db.insert_measurement(session, 1, sample_measurement)
    second = db.insert_measurement(session, 1, sample_measurement)
    assert first is True
    assert second is False

    count = session.execute(
        select(func.count()).select_from(Measurement).where(Measurement.city_id == 1)
    ).scalar_one()
    assert count == 1


def test_insert_measurement_different_timestamps(session, sample_measurement):
    db.insert_measurement(session, 1, sample_measurement)
    second = dict(sample_measurement, timestamp="2024-01-15T12:30:00Z", temp_c=6.0)
    db.insert_measurement(session, 1, second)

    rows = session.execute(
        select(Measurement.timestamp)
        .where(Measurement.city_id == 1)
        .order_by(Measurement.timestamp)
    ).all()
    assert len(rows) == 2


def test_load_latest_per_city_filtered(tmp_path, sample_measurement):
    # data_loader otwiera bazę read-only (URI file:...?mode=ro), więc zamiast
    # bazy w pamięci tworzymy plikową bazę tymczasową (bez WAL, by ro ją widział).
    from dashboard.data_loader import load_latest_per_city_filtered

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        s.add(City(name="Warsaw", country="PL", lat=52.23, lon=21.01))
        s.add(City(name="Berlin", country="DE", lat=52.52, lon=13.40))
        s.commit()
        # 2 pomiary per miasto — drugi nowszy
        for city_id, ts, temp in [
            (1, "2024-01-15T10:00:00Z", 1.0),
            (1, "2024-01-15T12:00:00Z", 5.2),
            (2, "2024-01-15T10:00:00Z", 2.0),
            (2, "2024-01-15T12:00:00Z", 7.0),
        ]:
            db.insert_measurement(s, city_id, dict(sample_measurement, timestamp=ts, temp_c=temp))
        s.commit()

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


def test_log_collection_run(session):
    db.log_collection_run(session, cities_ok=18, cities_failed=2, source_used="owm:18", notes="failed: X,Y")
    row = session.execute(select(CollectionLog)).scalar_one()
    assert row.cities_ok == 18
    assert row.cities_failed == 2
    assert row.source_used == "owm:18"
    assert "failed" in row.notes
    assert row.run_at.endswith("Z")
