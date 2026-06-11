"""Testy parsera backfillu — mapowanie bloku hourly z Open-Meteo na wiersze do bazy."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backfill import _hourly_to_rows, _normalize_ts

# Przykładowy blok hourly jak z odpowiedzi Open-Meteo.
# Środkowa godzina ma None w temperature_2m (brak danych) — ma zostać pominięta.
HOURLY = {
    "time": ["2026-06-10T10:00", "2026-06-10T11:00", "2026-06-10T12:00"],
    "temperature_2m": [10.0, None, 12.0],
    "apparent_temperature": [9.0, None, 11.5],
    "relativehumidity_2m": [80, None, 75.6],
    "pressure_msl": [1013.2, None, 1012.0],
    "windspeed_10m": [3.6, None, 7.2],
    "winddirection_10m": [180, None, 270],
    "cloudcover": [50, None, 100],
    "weathercode": [3, None, 61],
}


def test_hourly_to_rows_mapping():
    rows = _hourly_to_rows(HOURLY)
    assert len(rows) == 2  # godzina z None w temperaturze pominięta

    r = rows[0]
    assert r["timestamp"] == "2026-06-10T10:00:00Z"
    assert r["temp_c"] == 10.0
    assert r["feels_like_c"] == 9.0
    assert r["humidity_pct"] == 80
    assert r["pressure_hpa"] == 1013       # zaokrąglone do int
    assert r["wind_speed_ms"] == 1.0       # 3.6 km/h -> 1.0 m/s
    assert r["wind_deg"] == 180
    assert r["clouds_pct"] == 50
    assert r["weather_main"] == "Clouds"   # kod WMO 3 = zachmurzenie
    assert r["weather_desc"] == "overcast"
    assert r["source"] == "open_meteo"

    assert rows[1]["weather_main"] == "Rain"  # kod WMO 61


def test_hourly_to_rows_cutoff_skips_future():
    # cutoff w środku zakresu — godziny po nim (prognoza) mają wypaść
    rows = _hourly_to_rows(HOURLY, cutoff="2026-06-10T11:30:00Z")
    assert [r["timestamp"] for r in rows] == ["2026-06-10T10:00:00Z"]


def test_hourly_to_rows_empty():
    assert _hourly_to_rows({}) == []
    assert _hourly_to_rows({"time": []}) == []


def test_normalize_ts():
    assert _normalize_ts("2026-06-10T10:00") == "2026-06-10T10:00:00Z"
    assert _normalize_ts("2026-06-10T10:00:00Z") == "2026-06-10T10:00:00Z"
