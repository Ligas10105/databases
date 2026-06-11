"""Time series tab: line chart of selected parameter over time, per city."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from dashboard.data_loader import PARAM_COLUMNS, load_measurements


def render(db_path: str, filters: dict) -> None:
    st.subheader("Time series")
    df = load_measurements(db_path, filters)
    if df.empty:
        st.info("No data for current filters.")
        return

    parameter = filters.get("parameter", "temperature")
    column = PARAM_COLUMNS[parameter]
    aggregation = filters.get("aggregation", "raw")

    # Etykieta osi X dopasowana do poziomu agregacji (tygodniowa to numer
    # tygodnia ISO '2026-W23', nie czas UTC, więc nie kłamiemy w opisie osi).
    x_label = {
        "weekly": "Week (ISO)",
        "daily": "Day (UTC)",
        "hourly": "Hour (UTC)",
    }.get(aggregation, "Time (UTC)")

    # Gdy na miasto wypada mało punktów (np. tygodniowa nad krótkim zakresem =
    # 1 kubełek), linia bez markerów jest niewidoczna — wtedy włączamy markery.
    max_points = int(df.groupby("city")["timestamp"].nunique().max())
    markers = max_points <= 31

    fig = px.line(
        df,
        x="timestamp",
        y=column,
        color="city",
        markers=markers,
        labels={column: parameter, "timestamp": x_label},
        title=f"{parameter} over time ({aggregation})",
    )
    fig.update_layout(legend_title_text="City", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Show data table"):
        st.dataframe(df, use_container_width=True)
