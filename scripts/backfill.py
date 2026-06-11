"""Backfill — zasilenie bazy prawdziwą historią pogody (rozdzielczość godzinowa).

Dwa tryby:
  --start/--end  (GŁÓWNY) — Open-Meteo Historical Weather API (reanaliza ERA5),
                 jawny zakres dat YYYY-MM-DD. Uwaga: archiwum bywa opóźnione
                 o ok. 2-5 dni, najświeższe godziny mogą być puste — to normalne.
  --days N       (alternatywa) — /v1/forecast z past_days (max 92 dni wstecz).

Uruchomienie:
  python scripts/backfill.py --start 2026-05-28 --end 2026-06-08
  python scripts/backfill.py --days 14
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime
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
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
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


def _hourly_to_rows(hourly: dict) -> list[dict]:
    """Mapuje blok `hourly` z odpowiedzi Open-Meteo na wiersze do tabeli measurements.

    Wspólne dla obu trybów (forecast z past_days oraz archive) — oba API
    zwracają identyczną strukturę: time[], temperature_2m[], itd.
    Godziny bez danych (None w temperature_2m — np. opóźnienie archiwum ERA5)
    są pomijane, nie traktujemy ich jako błąd.
    """
    times = hourly.get("time") or []
    rows: list[dict] = []
    for i, t in enumerate(times):
        def at(key: str):
            arr = hourly.get(key) or []
            return arr[i] if i < len(arr) else None

        if at("temperature_2m") is None:
            continue

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


def _fetch_hourly(url: str, params: dict, city_name: str, timeout: int) -> list[dict] | None:
    """Wspólny GET + parsowanie. Zwraca wiersze, [] gdy brak danych, None przy błędzie."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("HTTP fail for %s: %s", city_name, exc)
        return None
    except ValueError as exc:
        logger.warning("Bad JSON for %s: %s", city_name, exc)
        return None
    return _hourly_to_rows(payload.get("hourly") or {})


def fetch_history(city: dict, past_days: int, timeout: int = 20) -> list[dict] | None:
    """Tryb --days: ostatnie N dni z /v1/forecast (past_days)."""
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "past_days": past_days,
        "forecast_days": 1,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "GMT",
    }
    return _fetch_hourly(OPEN_METEO_URL, params, city["name"], timeout)


def fetch_archive(city: dict, start_date: str, end_date: str, timeout: int = 20) -> list[dict] | None:
    """Tryb --start/--end: jawny zakres dat z Historical Weather API (reanaliza ERA5)."""
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "GMT",
    }
    return _fetch_hourly(ARCHIVE_URL, params, city["name"], timeout)


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


def _parse_date(value: str) -> date:
    """Waliduje format YYYY-MM-DD; przy błędzie argparse pokaże czytelny komunikat."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"niepoprawna data: {value!r} — oczekiwany format YYYY-MM-DD, np. 2026-05-28"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historii pogody. Tryb główny: --start/--end (archiwum ERA5)."
    )
    parser.add_argument("--start", type=_parse_date, default=None,
                        help="początek zakresu YYYY-MM-DD (Historical Weather API)")
    parser.add_argument("--end", type=_parse_date, default=None,
                        help="koniec zakresu YYYY-MM-DD (Historical Weather API)")
    parser.add_argument("--days", type=int, default=14,
                        help="alternatywa: ile dni wstecz z /v1/forecast (max 92)")
    parser.add_argument("--sleep", type=float, default=0.3, help="seconds between API calls")
    args = parser.parse_args()

    use_archive = args.start is not None or args.end is not None
    if use_archive:
        if args.start is None or args.end is None:
            parser.error("--start i --end muszą być podane razem")
        if args.start > args.end:
            parser.error(f"--start ({args.start}) musi być <= --end ({args.end})")
    elif not 1 <= args.days <= 92:
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

            if use_archive:
                rows = fetch_archive(city, args.start.isoformat(), args.end.isoformat())
            else:
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

        if use_archive:
            source_used = f"open_meteo_archive ({args.start}..{args.end})"
        else:
            source_used = f"open_meteo_archive (past_days={args.days})"
        log_collection_run(
            conn,
            cities_ok=cities_ok,
            cities_failed=cities_failed,
            source_used=source_used,
            notes=f"backfill: inserted={total_inserted} dup={total_dup}"
                  + (f" failed={','.join(failed_names)}" if failed_names else ""),
        )
        logger.info("DONE: cities ok=%d failed=%d | rows inserted=%d dup=%d",
                    cities_ok, cities_failed, total_inserted, total_dup)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
