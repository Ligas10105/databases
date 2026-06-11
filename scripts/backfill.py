"""Backfill — logowanie historii pogody z Open-Meteo do bazy (rozdzielczość godzinowa).

Pobiera ostatnie N dni (parametr past_days API, max 92) godzina po godzinie
dla wszystkich miast z config.yaml i wstawia do tabeli measurements.
Godziny z przyszłości (API zwraca też prognozę na resztę dzisiejszej doby)
są odcinane — logujemy tylko to, co już się wydarzyło.

Dzięki UNIQUE(city_id, timestamp) + INSERT OR IGNORE skrypt można odpalać
wielokrotnie — dokleja tylko nowe godziny, duplikaty pomija.

Uruchomienie:
  python scripts/backfill.py --days 14
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.db import get_city_id, get_connection, insert_measurement, log_collection_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = [
    "temperature_2m",
    "apparent_temperature",
    "relativehumidity_2m",
    "pressure_msl",
    "windspeed_10m",
    "winddirection_10m",
    "cloudcover",
    "weathercode",
]

# Mapowanie kodów pogody WMO (kolumna weathercode w Open-Meteo)
# na kategorię (weather_main) i opis (weather_desc).
_WMO_MAIN = {
    0: "Clear",
    1: "Clear", 2: "Clouds", 3: "Clouds",
    45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    56: "Drizzle", 57: "Drizzle",
    61: "Rain", 63: "Rain", 65: "Rain",
    66: "Rain", 67: "Rain",
    71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
    80: "Rain", 81: "Rain", 82: "Rain",
    85: "Snow", 86: "Snow",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

_WMO_DESC = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


def _wmo_to_main(code: int | None) -> str | None:
    if code is None:
        return None
    return _WMO_MAIN.get(int(code), "Unknown")


def _wmo_to_desc(code: int | None) -> str | None:
    if code is None:
        return None
    return _WMO_DESC.get(int(code), "unknown")


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_ts(t: str) -> str:
    """Open-Meteo zwraca 'YYYY-MM-DDTHH:MM' (UTC); w bazie trzymamy 'YYYY-MM-DDTHH:MM:SSZ'."""
    if len(t) == 16:
        return t + ":00Z"
    if t.endswith("Z"):
        return t
    return t + "Z"


def _to_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _kmh_to_ms(v):
    if v is None:
        return None
    try:
        return round(float(v) / 3.6, 2)
    except (TypeError, ValueError):
        return None


def _hourly_to_rows(hourly: dict, cutoff: str | None = None) -> list[dict]:
    """Mapuje blok `hourly` z odpowiedzi Open-Meteo na wiersze do tabeli measurements.

    Pomijamy godziny bez danych (None w temperature_2m) oraz godziny późniejsze
    niż `cutoff` (ISO UTC) — to prognoza na resztę doby, nie zapis przeszłości.
    Timestampy ISO porównują się poprawnie jako tekst (sortowanie leksykalne).
    """
    times = hourly.get("time") or []
    rows: list[dict] = []
    for i, t in enumerate(times):
        def at(key: str):
            arr = hourly.get(key) or []
            return arr[i] if i < len(arr) else None

        ts = _normalize_ts(t)
        if cutoff is not None and ts > cutoff:
            continue
        if at("temperature_2m") is None:
            continue

        wcode = at("weathercode")
        rows.append({
            "timestamp": ts,
            "temp_c": at("temperature_2m"),
            "feels_like_c": at("apparent_temperature"),
            "temp_min_c": None,
            "temp_max_c": None,
            "humidity_pct": _to_int(at("relativehumidity_2m")),
            "pressure_hpa": _to_int(at("pressure_msl")),
            "wind_speed_ms": _kmh_to_ms(at("windspeed_10m")),
            "wind_deg": _to_int(at("winddirection_10m")),
            "clouds_pct": _to_int(at("cloudcover")),
            "weather_main": _wmo_to_main(int(wcode)) if wcode is not None else None,
            "weather_desc": _wmo_to_desc(int(wcode)) if wcode is not None else None,
            "source": "open_meteo",
        })
    return rows


def fetch_history(city: dict, past_days: int, cutoff: str, timeout: int = 20) -> list[dict] | None:
    """Pobiera ostatnie `past_days` dni dla miasta. Zwraca wiersze albo None przy błędzie."""
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "past_days": past_days,
        "forecast_days": 1,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "GMT",
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("HTTP fail for %s: %s", city["name"], exc)
        return None
    except ValueError as exc:
        logger.warning("Bad JSON for %s: %s", city["name"], exc)
        return None
    return _hourly_to_rows(payload.get("hourly") or {}, cutoff=cutoff)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Logowanie historii pogody z Open-Meteo do bazy SQLite."
    )
    parser.add_argument("--days", type=int, default=14,
                        help="ile dni wstecz pobrać (1..92, domyślnie 14)")
    parser.add_argument("--sleep", type=float, default=0.3,
                        help="pauza w sekundach między miastami (nie przeciążamy API)")
    args = parser.parse_args()
    if not 1 <= args.days <= 92:
        parser.error("--days must be in 1..92")

    config = load_config()
    db_path = PROJECT_ROOT / config.get("database", {}).get("path", "data/weather.db")
    cities = config["collection"]["cities"]
    # Odcinamy godziny z przyszłości względem chwili startu skryptu.
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(db_path)
    total_inserted = 0
    total_dup = 0
    cities_ok = 0
    cities_failed = 0
    failed_names: list[str] = []

    try:
        for city in cities:
            city_id = get_city_id(conn, city["name"], city["country"])
            if city_id is None:
                logger.warning("missing city in DB: %s,%s", city["name"], city["country"])
                cities_failed += 1
                failed_names.append(city["name"])
                continue

            rows = fetch_history(city, args.days, cutoff)
            if rows is None:
                cities_failed += 1
                failed_names.append(city["name"])
                continue

            ins = 0
            dup = 0
            for row in rows:
                if insert_measurement(conn, city_id, row):
                    ins += 1
                else:
                    dup += 1
            total_inserted += ins
            total_dup += dup
            cities_ok += 1
            logger.info("%-12s %s,%s rows=%d inserted=%d dup=%d",
                        "[backfill]", city["name"], city["country"], len(rows), ins, dup)
            time.sleep(args.sleep)

        log_collection_run(
            conn,
            cities_ok=cities_ok,
            cities_failed=cities_failed,
            source_used=f"open_meteo (past_days={args.days})",
            notes=f"backfill: inserted={total_inserted} dup={total_dup}"
                  + (f" failed={','.join(failed_names)}" if failed_names else ""),
        )
        logger.info("DONE: cities ok=%d failed=%d | rows inserted=%d dup=%d",
                    cities_ok, cities_failed, total_inserted, total_dup)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
