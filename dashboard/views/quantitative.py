"""Statistics tab: summary table, histogram, box plot for selected parameter."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from dashboard.data_loader import PARAM_COLUMNS, load_measurements


def render(db_path: str, filters: dict) -> None:
    st.subheader("Statistics")
    df = load_measurements(db_path, filters)
    if df.empty:
        st.info("No data for current filters.")
        return

    parameter = filters.get("parameter", "temperature")
    column = PARAM_COLUMNS[parameter]
    series = df[column].dropna()
    if series.empty:
        st.info(f"No values available for '{parameter}'.")
        return

    summary = (
        df.groupby("city")[column]
        .agg(["min", "max", "mean", "std", "count"])
        .round(2)
        .reset_index()
        .rename(columns={"city": "City"})
    )
    st.markdown(f"**Summary per city — {parameter}**")
    st.dataframe(summary, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        hist = px.histogram(
            df, x=column, nbins=40,
            title=f"Distribution of {parameter}",
            labels={column: parameter},
        )
        st.plotly_chart(hist, use_container_width=True)
    with col2:
        box = px.box(
            df, x="city", y=column, points="outliers",
            title=f"{parameter} per city",
            labels={column: parameter, "city": "City"},
        )
        box.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(box, use_container_width=True)
