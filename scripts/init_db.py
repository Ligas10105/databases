"""Inicjalizacja bazy: utworzenie schematu (z modeli ORM) i wstawienie miast.

Schemat NIE jest już budowany ręcznym CREATE TABLE — powstaje z deklaratywnych
modeli w `collector.models` przez `Base.metadata.create_all`. Miasta z config.yaml
wstawiamy przez ORM, pomijając już istniejące (idempotentnie).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.db import get_engine
from collector.models import Base, City

CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_db(db_path: Path, cities: list[dict]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    # Tworzymy tabele i indeksy na podstawie modeli ORM (CREATE TABLE IF NOT EXISTS).
    Base.metadata.create_all(engine)

    with Session(engine, future=True) as session:
        for city in cities:
            exists = session.execute(
                select(City.id).where(
                    City.name == city["name"], City.country == city["country"]
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(
                    City(
                        name=city["name"],
                        country=city["country"],
                        lat=city["lat"],
                        lon=city["lon"],
                    )
                )
        session.commit()
        count = session.execute(select(func.count()).select_from(City)).scalar_one()

    print(f"DB initialized at {db_path}. Cities in DB: {count}")


def main() -> None:
    config = load_config()
    db_path = PROJECT_ROOT / config.get("database", {}).get("path", "data/weather.db")
    cities = config["collection"]["cities"]
    init_db(db_path, cities)


if __name__ == "__main__":
    main()
