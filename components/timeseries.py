import random
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

pio.templates.default = "plotly_dark"

COLORS = [
    "#60a5fa", "#f472b6", "#34d399", "#fbbf24", "#a78bfa",
    "#fb923c", "#4ade80", "#f87171", "#818cf8", "#2dd4bf",
]


def render_ndvi_timeseries(timeseries_df, parcels, risks, n_lines=10):
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("NDVI Time Series — Selected Parcels", "Risk Score Distribution"),
        vertical_spacing=0.18,
    )

    n_lines = max(1, min(n_lines, len(parcels)))

    sorted_idx = sorted(range(len(parcels)), key=lambda i: risks[i]["risk_score"])

    selected = set()
    selected.add(sorted_idx[0])
    selected.add(sorted_idx[-1])

    rest = [i for i in sorted_idx[1:-1] if len(selected) < n_lines]
    rest = random.Random(str(hash(str(parcels)))).sample(
        rest, min(len(rest), n_lines - len(selected))
    )
    selected.update(rest)

    for idx, i in enumerate(sorted(selected)):
        p = parcels[i]
        r = risks[i]
        pid = p["id"]
        if pid not in timeseries_df.columns:
            continue
        color = COLORS[idx % len(COLORS)]
        label = f"{pid} ({p['crop']}) — Risk: {r['risk_score']:.0f}"
        fig.add_trace(
            go.Scatter(
                x=timeseries_df.index,
                y=timeseries_df[pid],
                mode="lines+markers",
                name=label,
                line={"width": 2, "color": color},
                marker={"size": 5},
            ),
            row=1, col=1,
        )

    scores = [r["risk_score"] for r in risks]
    fig.add_trace(
        go.Histogram(
            x=scores,
            nbinsx=20,
            marker_color="#60a5fa",
            marker_line_color="#1e293b",
            marker_line_width=1,
            name="Risk Score",
        ),
        row=2, col=1,
    )

    fig.update_layout(
        height=550,
        barmode="overlay",
        hovermode="x unified",
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
        paper_bgcolor="#0e1117",
        plot_bgcolor="#1e293b",
        font={"color": "#e2e8f0"},
        legend={"font": {"color": "#e2e8f0"}},
    )
    fig.update_xaxes(title_text="Date", row=1, col=1, color="#94a3b8", gridcolor="#334155")
    fig.update_yaxes(title_text="NDVI", row=1, col=1, range=[0, 1], color="#94a3b8", gridcolor="#334155")
    fig.update_xaxes(title_text="Risk Score", row=2, col=1, color="#94a3b8", gridcolor="#334155")
    fig.update_yaxes(title_text="Count", row=2, col=1, color="#94a3b8", gridcolor="#334155")

    st.plotly_chart(fig, use_container_width=True)
