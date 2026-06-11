"""Modele ORM (SQLAlchemy) — deklaratywna definicja schematu bazy.

Cały schemat opisany jest tutaj jako klasy mapowane na tabele. Dzięki temu
jedna definicja modeli służy zarówno do tworzenia bazy (init_db przez
Base.metadata.create_all), jak i do zapisu (backfill) oraz odczytu
(dashboard) — wszystko przez ORM, bez ręcznego CREATE TABLE / surowego SQL.

Odwzorowanie 1:1 poprzedniego schematu:
- cities          — miasta (UNIQUE(name, country)),
- measurements    — pomiary godzinowe (UNIQUE(city_id, timestamp) + 2 indeksy),
- collection_log  — log uruchomień backfillu.

Timestampy trzymamy jako TEXT (ISO 8601 UTC z 'Z'), zgodnie z zasadami projektu.
"""
from __future__ import annotations

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Wspólna baza deklaratywna dla wszystkich modeli."""


class City(Base):
    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("name", "country", name="uq_cities_name_country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    measurements: Mapped[list["Measurement"]] = relationship(
        back_populates="city", cascade="all, delete-orphan"
    )


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("city_id", "timestamp", name="uq_measurements_city_ts"),
        Index("idx_measurements_city_time", "city_id", "timestamp"),
        Index("idx_measurements_time", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    temp_c: Mapped[float | None] = mapped_column(Float)
    feels_like_c: Mapped[float | None] = mapped_column(Float)
    temp_min_c: Mapped[float | None] = mapped_column(Float)
    temp_max_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[int | None] = mapped_column(Integer)
    pressure_hpa: Mapped[int | None] = mapped_column(Integer)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float)
    wind_deg: Mapped[int | None] = mapped_column(Integer)
    clouds_pct: Mapped[int | None] = mapped_column(Integer)
    weather_main: Mapped[str | None] = mapped_column(Text)
    weather_desc: Mapped[str | None] = mapped_column(Text)
    # DEFAULT 'open_meteo' w DDL (server_default) — zgodnie z poprzednim schematem.
    source: Mapped[str | None] = mapped_column(Text, server_default=text("'open_meteo'"))

    city: Mapped["City"] = relationship(back_populates="measurements")


class CollectionLog(Base):
    __tablename__ = "collection_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[str] = mapped_column(Text, nullable=False)
    cities_ok: Mapped[int | None] = mapped_column(Integer)
    cities_failed: Mapped[int | None] = mapped_column(Integer)
    source_used: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
