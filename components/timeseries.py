import random
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

pio.templates.default = "plotly_dark"

COLORS = [
    "#5a7d3c", "#a67c52", "#8cb369", "#d4a373", "#7a9d54",
    "#b8956a", "#6b8e4a", "#c49a6c", "#588157", "#9b8562",
]

MOBILE_FONT = 10


def _selected_indices(parcels, risks, n_lines):
    n_lines = max(1, min(n_lines, len(parcels)))
    sorted_idx = sorted(range(len(parcels)), key=lambda i: risks[i]["risk_score"])
    selected = {sorted_idx[0], sorted_idx[-1]}
    rest = [i for i in sorted_idx[1:-1] if len(selected) < n_lines]
    rest = random.Random(str(hash(str(parcels)))).sample(
        rest, min(len(rest), n_lines - len(selected))
    )
    selected.update(rest)
    return sorted(selected)


def render_ndvi_timeseries(timeseries_df, timeseries_srre_df, parcels, risks,
                           n_lines=10, wofost_results=None, nutrient_results=None):
    has_wofost = bool(wofost_results and nutrient_results)
    n_rows = 4 if has_wofost else 3

    titles = [
        "NDVI Time Series — Selected Parcels",
        "SRRE (B08/B05) Time Series — Selected Parcels",
        "Risk Score Distribution",
    ]
    if has_wofost:
        titles.append("N Surplus Distribution (kg/ha)")

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        subplot_titles=titles,
        vertical_spacing=0.12,
    )

    selected = _selected_indices(parcels, risks, n_lines)

    for idx, i in enumerate(selected):
        p = parcels[i]
        r = risks[i]
        pid = p["id"]
        color = COLORS[idx % len(COLORS)]
        label = f"{pid} ({p['crop']}) — Risk: {r['risk_score']:.0f}"

        for ts_df, row, col, name in [
            (timeseries_df, 1, 1, label),
            (timeseries_srre_df, 2, 1, label),
        ]:
            if pid not in ts_df.columns:
                continue
            fig.add_trace(
                go.Scatter(
                    x=ts_df.index,
                    y=ts_df[pid],
                    mode="lines+markers",
                    name=name,
                    line={"width": 2, "color": color},
                    marker={"size": 5},
                    showlegend=(row == 1),
                ),
                row=row, col=col,
            )

    scores = [r["risk_score"] for r in risks]
    fig.add_trace(
        go.Histogram(
            x=scores, nbinsx=20,
            marker_color="#7a9d54",
            marker_line_color="#ffffff",
            marker_line_width=1,
            name="Risk Score",
        ),
        row=3, col=1,
    )

    if has_wofost:
        n_surplus_vals = [
            n.get("n_surplus_kg_ha", 0) for n in nutrient_results
            if n.get("n_surplus_kg_ha") is not None
        ]
        if n_surplus_vals:
            fig.add_trace(
                go.Histogram(
                    x=n_surplus_vals, nbinsx=20,
                    marker_color="#8cb369",
                    marker_line_color="#ffffff",
                    marker_line_width=1,
                    name="N Surplus",
                ),
                row=4, col=1,
            )

    fig.update_layout(
        height=450 if has_wofost else 400,
        barmode="overlay",
        hovermode="x unified",
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        paper_bgcolor="#f2efe9",
        plot_bgcolor="#ffffff",
        font={"color": "#4a3f35", "size": MOBILE_FONT},
        legend={"font": {"color": "#4a3f35", "size": 9}, "itemsizing": "constant"},
        hoverlabel={"font": {"size": MOBILE_FONT}},
    )
    fig.update_xaxes(title_text="Date", row=1, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    fig.update_yaxes(title_text="NDVI", row=1, col=1, range=[0, 1], color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    fig.update_xaxes(title_text="Date", row=2, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    fig.update_yaxes(title_text="SRRE", row=2, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    fig.update_xaxes(title_text="Risk Score", row=3, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    fig.update_yaxes(title_text="Count", row=3, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    if has_wofost:
        fig.update_xaxes(title_text="N Surplus (kg/ha)", row=4, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
        fig.update_yaxes(title_text="Count", row=4, col=1, color="#7a6b5d", gridcolor="#d4c9b8", title_font={"size": MOBILE_FONT}, tickfont={"size": 9})
    for annotation in fig['layout']['annotations']:
        annotation['font']['size'] = 11

    st.plotly_chart(fig, width='stretch')


def render_wofost_summary(wofost_results, nutrient_results, parcels, risks):
    if not wofost_results:
        return

    col1, col2, col3, col4 = st.columns(4)
    yields = [w.get("yield_kg_ha", 0) or 0 for w in wofost_results]
    avg_yield = sum(yields) / max(len(yields), 1)
    col1.metric("Avg Predicted Yield", f"{avg_yield:.0f} kg/ha")

    n_surplus_vals = [n.get("n_surplus_kg_ha", 0) or 0 for n in nutrient_results] if nutrient_results else []
    total_surplus = sum(n_surplus_vals)
    col2.metric("Total N Surplus", f"{total_surplus:.0f} kg")

    high_risk = sum(1 for n in nutrient_results or []
                    if n.get("overfertilization_risk_level") in ("High", "Critical"))
    col3.metric("High N-Risk Parcels", high_risk)

    fallbacks = sum(1 for w in wofost_results if w.get("fallback_flags"))
    col4.metric("Fallback Mappings", fallbacks)

    fig = go.Figure()
    yields_ok = [w.get("yield_kg_ha", 0) or 0 for w in wofost_results]
    fig.add_trace(go.Scatter(
        x=list(range(len(yields_ok))),
        y=yields_ok,
        mode="markers",
        marker={"color": "#8cb369", "size": 8},
        name="Predicted yield",
    ))
    fig.update_layout(
        height=180,
        title="Predicted Yield per Parcel (kg/ha)",
        title_font={"size": 12},
        margin={"l": 10, "r": 10, "t": 25, "b": 10},
        paper_bgcolor="#f2efe9",
        plot_bgcolor="#ffffff",
        font={"color": "#4a3f35", "size": MOBILE_FONT},
        xaxis={"color": "#7a6b5d", "gridcolor": "#d4c9b8", "tickfont": {"size": 9}},
        yaxis={"color": "#7a6b5d", "gridcolor": "#d4c9b8", "tickfont": {"size": 9}},
    )
    st.plotly_chart(fig, width='stretch')
