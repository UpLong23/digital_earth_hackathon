import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from config import CROP_N_DEMAND, DEFAULT_LAT, DEFAULT_LON, DEFAULT_BUFFER_DEG
from backend.parcels import load_parcels, filter_parcels
from backend.risk import risk_label
from backend.data import build_demo_data
from components.sidebar import render_sidebar
from components.map import render_risk_map
from components.timeseries import render_ndvi_timeseries, render_wofost_summary

MAX_MAP_PARCELS = 2000                                                                                          # TODO

st.set_page_config(page_title="Gödslingskollen", page_icon="🌾", layout="wide")

st.markdown("""
<style>
.stApp { background: #0e1117; }
[data-testid="stHeader"] { background: linear-gradient(90deg, #0f172a, #1e3a5f); }
h1, h2, h3, h4, h5, h6 { color: #e2e8f0 !important; }
p, li, .stMarkdown { color: #e2e8f0; }
[data-testid="stSidebar"] { background: #0f172a; }
[data-testid="stSidebar"] .stMarkdown { color: #e2e8f0; }
.stAlert { background: #1e293b; border-left: 4px solid #22c55e; color: #e2e8f0; }
[data-testid="stMetricValue"] { color: #e2e8f0; }
[data-testid="stMetricLabel"] { color: #94a3b8; }
[data-testid="stExpander"] { background: #1e293b; border: 1px solid #334155; }
.stDataFrame { background: #1e293b; color: #e2e8f0; }
[data-testid="stDataFrame"] td { color: #e2e8f0; }
[data-testid="stDataFrame"] th { background: #0f172a; color: #94a3b8; }
[data-testid="stDownloadButton"] button { background: #1e3a5f; color: #e2e8f0; border: 1px solid #334155; }
.st-bb { background-color: #1e293b !important; }
.st-at { background-color: #1e293b !important; }
[data-testid="stVerticalBlock"] > [style*="flex"] > [data-testid="stVerticalBlock"] { background: transparent; }
div.row-widget.stRadio > div { color: #e2e8f0; }
.st-cb { color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)

sidebar_filters = render_sidebar()

lat = sidebar_filters["lat"]
lon = sidebar_filters["lon"]
selected_muni = sidebar_filters["municipality"]
is_muni_mode = selected_muni and selected_muni != "Custom location"

# Build a hash of current query params to detect changes
query_hash = hash((
    lat, lon, selected_muni,
    sidebar_filters["start_date"],
    sidebar_filters["end_date"],
    sidebar_filters["crop_type"],
    sidebar_filters["use_demo"],
    sidebar_filters["use_wofost"],
    sidebar_filters["use_nutrient"],
))
last_hash = st.session_state.get("last_query_hash")

if last_hash is None or last_hash != query_hash:
    from backend.lpis import fetch_lpis_parcels, is_cached, get_parcels_in_municipality
    from backend.parcels import generate_parcels

    @st.cache_resource(ttl=3600)
    def _warm_lpis_cache():
        if is_cached():
            from backend.lpis import _load_gdf
            _load_gdf()

    _warm_lpis_cache()

    if is_muni_mode and is_cached():
        lpis = get_parcels_in_municipality(selected_muni)
        if len(lpis) >= 3:
            st.session_state.parcels = lpis
            st.session_state.lpis_source = True
            from backend.municipalities import get_municipality_center
            center = get_municipality_center(selected_muni)
            if center:
                st.session_state.muni_center_lat = center[0]
                st.session_state.muni_center_lon = center[1]
        else:
            st.session_state.parcels = generate_parcels(
                lat or 62.0, lon or 15.0, count=10
            )
            st.session_state.lpis_source = False
    else:
        try:
            lpis = fetch_lpis_parcels(lat, lon, size_deg=0.12, max_features=100)
            if len(lpis) >= 3:
                st.session_state.parcels = lpis
                st.session_state.lpis_source = True
            else:
                raise ValueError(f"Only {len(lpis)} parcels found")
        except Exception:
            st.session_state.parcels = generate_parcels(
                lat, lon, count=10
            )
            st.session_state.lpis_source = False

    st.session_state.pop("demo_data", None)
    st.session_state.pop("real_data", None)
    st.session_state.pop("satellite_source", None)

st.session_state.last_query_hash = query_hash
use_demo = sidebar_filters["use_demo"]
all_parcels = st.session_state.parcels

if is_muni_mode:
    muni_center_lat = st.session_state.get("muni_center_lat", lat)
    muni_center_lon = st.session_state.get("muni_center_lon", lon)
    title = f"Overfertilization Risk Monitor — {selected_muni}"
else:
    muni_center_lat, muni_center_lon = lat, lon
    title = f"Overfertilization Risk Monitor ({lat:.3f}, {lon:.3f})"

st.markdown(
    f"<h1 style='display:inline;color:#e2e8f0;'>🌾 Gödslingskollen &nbsp;</h1>"
    f"<span style='color:#94a3b8;font-size:1.1rem;'>{title}</span>",
    unsafe_allow_html=True,
)

st.markdown(
    "<p style='color:#94a3b8;font-size:0.9rem;max-width:800px;'>"
    "Gödslingskollen detects possible overfertilization on Swedish farmland. "
    "Each field is scored 0–100 by comparing its NDVI/NDRE against same-crop peer fields, "
    "within-field heterogeneity, and terrain runoff potential. "
    "High scores mean elevated vigor relative to peers with high within-field variability — "
    "a pattern consistent with excessive nitrogen. "
    "Select a municipality or enter coordinates to explore field-level risks."
    "</p>",
    unsafe_allow_html=True,
)

if st.session_state.get("lpis_source"):
    total_area = sum(p["area_ha"] for p in all_parcels)
    n_fields = len(all_parcels)
    crops = set(p["crop"] for p in all_parcels if p["crop"] != "Unknown")
    loc_label = selected_muni if is_muni_mode else f"({lat:.3f}, {lon:.3f})"
    st.caption(f"🗺️ {n_fields} real LPIS parcels ({total_area:.0f} ha, {len(crops)} crop types) — {loc_label}")
    st.info(
        "ℹ️ **LPIS crop labels are from the latest annual declaration — they may not reflect actual sowing in your selected season.** "
        "WOFOST simulation uses these labels; if the crop changed, predicted yield may be inaccurate.",
        icon="📋",
    )

if use_demo:
    if "demo_data" not in st.session_state:
        st.session_state.demo_data = build_demo_data(parcels=all_parcels, lat=lat, lon=lon)
    dd = st.session_state.demo_data
    data_source_label = "📊 Demo data (synthetic)"
else:
    conn = st.session_state.get("conn")
    if not conn:
        if "demo_data" not in st.session_state:
            st.session_state.demo_data = build_demo_data(parcels=all_parcels, lat=lat, lon=lon)
        dd = st.session_state.demo_data
        data_source_label = "📊 Demo data (not connected)"
    else:
        from backend.real import build_real_data, build_real_data_from_satellite

        # Handle "Fetch real satellite data" button
        if st.session_state.pop("fetch_satellite", False):
            from datetime import date as dt_date
            s_start = dt_date.fromisoformat(sidebar_filters["start_date"])
            s_end = dt_date.fromisoformat(sidebar_filters["end_date"])
            total_days = (s_end - s_start).days
            if total_days > 90:
                # est = total_days // 3
                st.info(
                    f"Date range is {total_days} days. "
                    # f"Estimated fetch time is ~{est} min. "
                    "The progress bar below will show real-time status."
                )

            progress_bar = st.progress(0, text="Starting satellite data fetch...")
            _prev_pct = [0.0]
            def _cb(pct, msg):
                if pct is not None:
                    _prev_pct[0] = pct
                progress_bar.progress(_prev_pct[0], text=msg or "")

            sat_data, err = build_real_data_from_satellite(
                conn, all_parcels, lat, lon,
                sidebar_filters["start_date"], sidebar_filters["end_date"],
                progress_callback=_cb,
                municipality=selected_muni if is_muni_mode else None,
                use_wofost=sidebar_filters["use_wofost"],
            )
            if err:
                st.error(f"Satellite fetch failed: {err}")
            else:
                st.session_state.real_data = sat_data
                st.session_state.satellite_source = True
                st.rerun()

        if "real_data" not in st.session_state:
            with st.spinner("Computing risk scores..."):
                real_data, err = build_real_data(
                    conn, all_parcels, lat, lon, DEFAULT_BUFFER_DEG,
                    sidebar_filters["start_date"], sidebar_filters["end_date"],
                    use_wofost=sidebar_filters["use_wofost"],
                )
            if err:
                st.error(f"Real data fetch failed: {err}. Falling back to demo.")
                if "demo_data" not in st.session_state:
                    st.session_state.demo_data = build_demo_data(parcels=all_parcels, lat=lat, lon=lon)
                dd = st.session_state.demo_data
                data_source_label = "⚠️ Demo data (fetch error)"
            else:
                st.session_state.real_data = real_data
                dd = real_data
                data_source_label = "🧪 Synthetic model (connected)"
        else:
            dd = st.session_state.real_data
            data_source_label = (
                "🛰️ Real Copernicus satellite data"
                if st.session_state.get("satellite_source")
                else "🧪 Synthetic model (connected)"
            )

st.caption(data_source_label)

parcels = list(all_parcels)
if sidebar_filters["crop_type"] != "All":
    parcels = filter_parcels(parcels, crop_type=sidebar_filters["crop_type"])
    if not parcels:
        parcels = list(all_parcels)

parcel_ids = {p["id"] for p in parcels}
visible_indices = [i for i, p in enumerate(all_parcels) if p["id"] in parcel_ids]
visible_risks = [dd["risks"][i] for i in visible_indices]
visible_parcels = [all_parcels[i] for i in visible_indices]

# Limit map-rendered parcels to avoid Folium slowdown
if len(visible_parcels) > MAX_MAP_PARCELS:
    st.warning(
        f"Showing {MAX_MAP_PARCELS} of {len(visible_parcels)} parcels on map "
        f"(all {len(visible_parcels)} parcels included in computations)"
    )
    map_indices = sorted(
        range(len(visible_parcels)),
        key=lambda i: visible_risks[i]["risk_score"],
        reverse=True,
    )[:MAX_MAP_PARCELS]
    map_parcels = [visible_parcels[i] for i in map_indices]
    map_risks = [visible_risks[i] for i in map_indices]
else:
    map_parcels = visible_parcels
    map_risks = visible_risks

st.subheader("🗺️ Risk Map")
st.caption("Color-coded by overfertilization risk. Click for details.")
try:
    render_risk_map(
        map_parcels, map_risks,
        center_lat=muni_center_lat, center_lon=muni_center_lon,
        municipality=selected_muni if is_muni_mode else None,
    )
except Exception as e:
    st.error(f"Map error: {e}")

st.divider()

# ── Summary cards row ─────────────────────────────────────────────
try:
    scores = [r["risk_score"] for r in visible_risks]
    avg_risk = sum(scores) / len(scores)
    high = sum(1 for s in scores if s >= 60)
    critical = sum(1 for s in scores if s >= 80)
    moderate = sum(1 for s in scores if 30 <= s < 60)
    low = sum(1 for s in scores if s < 30)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Average Risk", f"{avg_risk:.0f}/100")
    with c2:
        st.metric("Critical", critical)
    with c3:
        st.metric("High Risk", high)
    with c4:
        st.metric("Moderate", moderate)
    with c5:
        st.metric("Low Risk", low)
except Exception as e:
    st.error(f"Summary error: {e}")

# ── Top risks + Crop distribution side by side ────────────────────
col_left, col_right = st.columns(2)
with col_left:
    st.subheader("🔴 Top 5 Highest Risk Parcels")
    sorted_data = sorted(zip(visible_risks, visible_parcels),
                         key=lambda x: x[0]["risk_score"], reverse=True)[:5]
    for r, p in sorted_data:
        lbl, clr = risk_label(r["risk_score"])
        st.markdown(
            f"<span style='display:inline-block;width:10px;height:10px;"
            f"background:{clr};border-radius:50%;'></span> "
            f"**{p['id']}** ({p['crop']}, {p['area_ha']:.1f} ha) — **{r['risk_score']:.0f}/100** ({lbl})",
            unsafe_allow_html=True,
        )

with col_right:
    st.subheader("🌾 Crop Distribution")
    crop_counts = pd.Series([p["crop"] for p in visible_parcels]).value_counts()
    fig_crop = go.Figure(go.Bar(
        x=crop_counts.values,
        y=crop_counts.index,
        orientation="h",
        marker_color="#60a5fa",
        text=crop_counts.values,
        textposition="outside",
    ))
    fig_crop.update_layout(
        height=250,
        margin={"l": 10, "r": 40, "t": 10, "b": 10},
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font={"color": "#e2e8f0"},
        xaxis={"title": "Parcels", "color": "#94a3b8", "gridcolor": "#334155"},
        yaxis={"color": "#94a3b8", "gridcolor": "#334155"},
        hovermode="y unified",
    )
    st.plotly_chart(fig_crop, use_container_width=True)

st.divider()
# ── WOFOST summary (if available) ──────────────────────────────────
if dd.get("wofost_results"):
    render_wofost_summary(
        dd["wofost_results"], dd.get("nutrient_results"),
        all_parcels, dd["risks"],
    )

    # ── Yield charts side by side ──────────────────────────────────
    ycol_left, ycol_right = st.columns(2)

    wofost_res = dd["wofost_results"]
    with ycol_left:
        st.subheader("📊 Total Yield per Crop Type")
        crop_yield = {}
        for p, w in zip(all_parcels, wofost_res):
            crop = p["crop"]
            area = p.get("area_ha", 0)
            yld = w.get("yield_kg_ha") or 0
            crop_yield[crop] = crop_yield.get(crop, 0) + yld * area
        cy_df = pd.Series(crop_yield).sort_values(ascending=True)
        if not cy_df.empty:
            fig_crop_yield = go.Figure(go.Bar(
                x=cy_df.values,
                y=cy_df.index,
                orientation="h",
                marker_color="#34d399",
                text=[f"{v:.0f} kg" for v in cy_df.values],
                textposition="outside",
            ))
            fig_crop_yield.update_layout(
                height=300,
                margin={"l": 10, "r": 40, "t": 10, "b": 10},
                paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font={"color": "#e2e8f0"},
                xaxis={"title": "Total Yield (kg)", "color": "#94a3b8", "gridcolor": "#334155"},
                yaxis={"color": "#94a3b8", "gridcolor": "#334155"},
                hovermode="y unified",
            )
            st.plotly_chart(fig_crop_yield, use_container_width=True)

    with ycol_right:
        st.subheader("🧺 Total Yield per Parcel")
        parcel_yield = []
        parcel_ids_list = []
        for p, w in zip(all_parcels, wofost_res):
            area = p.get("area_ha", 0)
            yld = w.get("yield_kg_ha") or 0
            parcel_yield.append(yld * area)
            parcel_ids_list.append(p["id"])
        if parcel_yield:
            fig_parcel_yield = go.Figure(go.Bar(
                x=parcel_ids_list,
                y=parcel_yield,
                marker_color="#60a5fa",
                text=[f"{v:.0f}" for v in parcel_yield],
                textposition="outside",
            ))
            fig_parcel_yield.update_layout(
                height=300,
                margin={"l": 10, "r": 40, "t": 10, "b": 80},
                paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font={"color": "#e2e8f0"},
                xaxis={"color": "#94a3b8", "gridcolor": "#334155", "tickangle": -45},
                yaxis={"title": "Total Yield (kg)", "color": "#94a3b8", "gridcolor": "#334155"},
                hovermode="x",
            )
            st.plotly_chart(fig_parcel_yield, use_container_width=True)

    st.divider()

st.subheader("📈 NDVI & SRRE Time Series")
st.caption("Highest-risk parcel (reddest line), lowest-risk parcel, and random samples in between.")
n_lines = st.slider("Parcel lines to show", 1, 10, 10,
                     help="Shows highest- and lowest-risk parcels plus random samples from the middle.")
try:
    render_ndvi_timeseries(
        dd["timeseries"], dd.get("timeseries_srre", dd["timeseries"]),
        all_parcels, dd["risks"], n_lines=n_lines,
        wofost_results=dd.get("wofost_results"),
        nutrient_results=dd.get("nutrient_results"),
    )
except Exception as e:
    st.error(f"Chart error: {e}")

with st.expander("📋 Full Parcel Data Table", expanded=False):
    try:
        srre_values = dd.get("srre", [None] * len(all_parcels))
        rows = []
        for i, p in enumerate(all_parcels):
            r = dd["risks"][i]
            lbl, _ = risk_label(r["risk_score"])
            row = {
                "Parcel": p["id"], "Crop": p["crop"],
                "Area (ha)": p["area_ha"],
                "NDVI": r["ndvi"], "NDRE": r["ndre"],
                "SRRE": srre_values[i] if i < len(srre_values) else None,
                "Heterog.": r.get("heterogeneity_score"),
                "Runoff": r.get("runoff_score"),
                "Conf.": r.get("confidence"),
                "Risk Score": r["risk_score"], "Risk Level": lbl,
            }
            wofost_yield = r.get("wofost_yield_kg_ha")
            if wofost_yield is not None:
                row["Yield (kg/ha)"] = round(wofost_yield, 0)
                row["Total Yield (kg)"] = round(wofost_yield * p["area_ha"], 0)
                row["Total Yield (t)"] = round(wofost_yield * p["area_ha"] / 1000, 2)
            n_surplus = r.get("nutrient_n_surplus_kg_ha")
            if n_surplus is not None:
                row["N Surplus (kg/ha)"] = round(n_surplus, 0)
                row["N Risk Level"] = r.get("nutrient_overfertilization_risk_level", "")
            rows.append(row)
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("⬇ Download CSV",
                           df.to_csv(index=False).encode("utf-8"),
                           "gödslingskollen_report.csv", "text/csv")
    except Exception as e:
        st.error(f"Table error: {e}")

st.divider()
for text in [
    "🛰️ **Sentinel-2** — NDVI, NDRE & SRRE for crop health & anomaly",
    "⛰️ **EU-DTM** — Slope analysis for runoff potential",
    "🗺️ **LPIS** — Parcel registry from Swedish Board of Agriculture",
    "🌱 **WOFOST** — Crop growth simulation for yield & N-uptake estimation",
    "🌤️ **Open-Meteo** — Daily weather data for WOFOST forcing",
    "🧪 **SoilGrids** — Soil properties for WOFOST parameterization",
]:
    st.markdown(text)
