"""Backfill historical hourly weather from Open-Meteo into the measurements table.

Uses /v1/forecast with past_days (up to 92). Default 14 days.
Run:  python scripts/backfill.py [--days N]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.api_client import _wmo_to_desc, _wmo_to_main
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


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_ts(t: str) -> str:
    """Open-Meteo returns 'YYYY-MM-DDTHH:MM' (UTC). We need 'YYYY-MM-DDTHH:MM:SSZ'."""
    if len(t) == 16:
        return t + ":00Z"
    if t.endswith("Z"):
        return t
    return t + "Z"


def fetch_history(city: dict, past_days: int, timeout: int = 20) -> list[dict] | None:
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

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []

    rows: list[dict] = []
    for i, t in enumerate(times):
        def at(key: str):
            arr = hourly.get(key) or []
            return arr[i] if i < len(arr) else None

        wcode = at("weathercode")
        rows.append({
            "timestamp": _normalize_ts(t),
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
            "source": "open_meteo_archive",
        })
    return rows


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="how many past days to fetch (max 92)")
    parser.add_argument("--sleep", type=float, default=0.3, help="seconds between API calls")
    args = parser.parse_args()
    if not 1 <= args.days <= 92:
        parser.error("--days must be in 1..92")

    config = load_config()
    db_path = PROJECT_ROOT / config.get("database", {}).get("path", "data/weather.db")
    cities = config["collection"]["cities"]

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

            rows = fetch_history(city, args.days)
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
            source_used=f"open_meteo_archive (past_days={args.days})",
            notes=f"backfill: inserted={total_inserted} dup={total_dup}"
                  + (f" failed={','.join(failed_names)}" if failed_names else ""),
        )
        logger.info("DONE: cities ok=%d failed=%d | rows inserted=%d dup=%d",
                    cities_ok, cities_failed, total_inserted, total_dup)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
