"""Streamlit entry point. Run with: streamlit run dashboard/app.py"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.data_loader import (
    PARAM_COLUMNS,
    get_value_range,
    list_cities,
    list_weather_conditions,
)
from dashboard.views import quantitative, spatial, time_series


@st.cache_data(ttl=60)
def _load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@st.cache_data(ttl=60)
def _cached_cities(db_path: str):
    return list_cities(db_path)


@st.cache_data(ttl=60)
def _cached_conditions(db_path: str):
    return list_weather_conditions(db_path)


@st.cache_data(ttl=60)
def _cached_value_range(db_path: str, parameter: str):
    return get_value_range(db_path, parameter)


def _build_sidebar(db_path: str) -> dict:
    st.sidebar.header("Filters")

    today = datetime.now(timezone.utc).date()
    default_start = today - timedelta(days=7)
    date_range = st.sidebar.date_input(
        "Date range",
        value=(default_start, today),
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = default_start, today

    cities_df = _cached_cities(db_path)
    city_options = {f"{r['name']}, {r['country']}": int(r["id"]) for _, r in cities_df.iterrows()}
    selected_city_labels = st.sidebar.multiselect(
        "Cities",
        options=list(city_options.keys()),
        default=list(city_options.keys()),
    )
    selected_city_ids = [city_options[label] for label in selected_city_labels]

    parameter = st.sidebar.selectbox(
        "Parameter",
        options=list(PARAM_COLUMNS.keys()),
        index=0,
    )

    vmin, vmax = _cached_value_range(db_path, parameter)
    if vmax > vmin:
        value_min, value_max = st.sidebar.slider(
            "Value range",
            min_value=float(vmin),
            max_value=float(vmax),
            value=(float(vmin), float(vmax)),
        )
    else:
        value_min, value_max = None, None

    aggregation = st.sidebar.selectbox(
        "Aggregation",
        options=["raw", "hourly", "daily", "weekly"],
        index=0,
    )

    conditions = _cached_conditions(db_path)
    selected_conditions = st.sidebar.multiselect(
        "Weather conditions",
        options=conditions,
        default=conditions,
    )

    if st.sidebar.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

    start_iso = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end_iso = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    return {
        "start": start_iso,
        "end": end_iso,
        "city_ids": selected_city_ids,
        "parameter": parameter,
        "value_min": value_min,
        "value_max": value_max,
        "weather_conditions": selected_conditions,
        "aggregation": aggregation,
    }


def main() -> None:
    st.set_page_config(page_title="Weather dashboard", layout="wide")
    st.title("European Weather Dashboard")

    config = _load_config()
    db_path = str(PROJECT_ROOT / config.get("database", {}).get("path", "data/weather.db"))

    if not Path(db_path).exists():
        st.error(
            f"Database not found at `{db_path}`. "
            "Run `python scripts/init_db.py` first, then `python scripts/backfill.py --days 14`."
        )
        return

    filters = _build_sidebar(db_path)

    tab_ts, tab_stats, tab_map = st.tabs(["Time Series", "Statistics", "Map"])
    with tab_ts:
        time_series.render(db_path, filters)
    with tab_stats:
        quantitative.render(db_path, filters)
    with tab_map:
        spatial.render(db_path, filters)


if __name__ == "__main__":
    main()
else:
    main()
