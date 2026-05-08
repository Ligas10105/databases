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

    fig = px.line(
        df,
        x="timestamp",
        y=column,
        color="city",
        markers=False,
        labels={column: parameter, "timestamp": "Time (UTC)"},
        title=f"{parameter} over time",
    )
    fig.update_layout(legend_title_text="City", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Show data table"):
        st.dataframe(df, use_container_width=True)
