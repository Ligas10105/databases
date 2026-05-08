"""APScheduler entry point: collect weather every N minutes for all cities."""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collector.api_client import fetch_open_meteo, fetch_owm
from collector.db import (
    get_city_id,
    get_connection,
    insert_measurement,
    log_collection_run,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("collector")


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_all_cities() -> None:
    config = load_config()
    db_path = PROJECT_ROOT / config.get("database", {}).get("path", "data/weather.db")
    cities = config["collection"]["cities"]
    api_key = os.getenv("OWM_API_KEY", "").strip()

    ok = 0
    failed = 0
    sources = Counter()
    failed_cities: list[str] = []

    conn = get_connection(db_path)
    try:
        for city in cities:
            data = None
            if api_key and api_key != "your_api_key_here":
                data = fetch_owm(city, api_key)
            if data is None:
                data = fetch_open_meteo(city)

            if data is None:
                failed += 1
                failed_cities.append(city["name"])
                logger.warning("FAIL %s,%s — both providers failed",
                               city["name"], city["country"])
                continue

            city_id = get_city_id(conn, city["name"], city["country"])
            if city_id is None:
                logger.warning("City %s,%s not found in DB — run init_db.py",
                               city["name"], city["country"])
                failed += 1
                failed_cities.append(city["name"])
                continue

            inserted = insert_measurement(conn, city_id, data)
            ok += 1
            sources[data["source"]] += 1
            status = "INS" if inserted else "DUP"
            logger.info("%s %s,%s %.1f°C [%s]",
                        status, city["name"], city["country"],
                        data.get("temp_c") or float("nan"), data["source"])

        source_used = ",".join(f"{src}:{n}" for src, n in sources.items()) or "none"
        notes = ("failed: " + ",".join(failed_cities)) if failed_cities else ""
        log_collection_run(conn, ok, failed, source_used, notes)
        logger.info("Run complete: ok=%d failed=%d sources=%s",
                    ok, failed, source_used)
    finally:
        conn.close()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    config = load_config()
    interval = int(config["collection"].get("interval_minutes", 30))

    logger.info("Running initial collection...")
    collect_all_cities()

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        collect_all_cities,
        "interval",
        minutes=interval,
        id="collect_all_cities",
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduler started — every %d minutes. Ctrl+C to stop.", interval)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
