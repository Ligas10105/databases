"""Spatial tab: Folium map with markers + heatmap of latest values."""
from __future__ import annotations

import folium
import streamlit as st
from folium.plugins import HeatMap
from streamlit_folium import folium_static

from dashboard.data_loader import PARAM_COLUMNS, load_latest_per_city


def render(db_path: str, filters: dict) -> None:
    st.subheader("Map — latest readings")
    df = load_latest_per_city(db_path)
    if df.empty:
        st.info("No data yet — start the collector to populate the database.")
        return

    parameter = filters.get("parameter", "temperature")
    column = PARAM_COLUMNS[parameter]

    map_df = df.dropna(subset=["lat", "lon"]).copy()
    if map_df.empty:
        st.info("No cities with coordinates.")
        return

    fmap = folium.Map(
        location=[map_df["lat"].mean(), map_df["lon"].mean()],
        zoom_start=4,
        tiles="OpenStreetMap",
    )

    for _, row in map_df.iterrows():
        value = row.get(column)
        ts = row.get("timestamp")
        ts_text = ts.strftime("%Y-%m-%d %H:%M UTC") if ts is not None and not str(ts) == "NaT" else "no data"
        value_text = f"{value:.1f}" if value is not None and not _is_nan(value) else "n/a"
        popup_html = (
            f"<b>{row['city']}, {row['country']}</b><br>"
            f"{parameter}: {value_text}<br>"
            f"weather: {row.get('weather_main') or 'n/a'}<br>"
            f"updated: {ts_text}"
        )
        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"{row['city']}: {value_text}",
            icon=folium.Icon(color="blue", icon="cloud"),
        ).add_to(fmap)

    heat_df = map_df.dropna(subset=[column])
    if not heat_df.empty:
        heat_data = [
            [r["lat"], r["lon"], float(r[column])]
            for _, r in heat_df.iterrows()
        ]
        HeatMap(heat_data, radius=25, blur=18).add_to(fmap)

    folium_static(fmap, width=1100, height=600)


def _is_nan(x) -> bool:
    try:
        return x != x
    except Exception:
        return False
