import streamlit as st
import folium
from streamlit.components.v1 import html as st_html
from backend.risk import risk_label


def render_risk_map(parcels, risks, center_lat=55.913, center_lon=13.107,
                    municipality=None):
    from backend.municipalities import get_municipality_polygon

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        control_scale=True,
        tiles="CartoDB dark_matter",
        attr="CartoDB",
    )

    if municipality and municipality != "Custom location":
        poly = get_municipality_polygon(municipality)
        if poly is not None:
            coords = [[c[1], c[0]] for c in poly.exterior.coords]
            folium.Polygon(
                locations=coords,
                color="#60a5fa",
                weight=2.5,
                fill=False,
                dash_array="8, 4",
                popup=folium.Popup(
                    f"<b>Municipality:</b> {municipality}", max_width=200
                ),
            ).add_to(m)
            west, south, east, north = poly.bounds
            m.fit_bounds([[south, west], [north, east]])

    for p, r in zip(parcels, risks):
        label, color = risk_label(r["risk_score"])
        coords = p["geometry"]["coordinates"][0]
        polygon_coords = [(c[1], c[0]) for c in coords]

        vigor_z = r.get("vigor_z", 0)
        het = r.get("heterogeneity_score", 0)
        conf = r.get("confidence", 0)

        folium.Polygon(
            locations=polygon_coords,
            color="#ffffff",
            weight=1.2,
            fill_color=color,
            fill_opacity=0.6,
            popup=folium.Popup(
                f"<div style='min-width:180px;'>"
                f"<b>Parcel:</b> {p['id']}<br>"
                f"<b>Crop:</b> {p['crop']}<br>"
                f"<b>Risk:</b> {r['risk_score']}/100 &mdash; {label}<br>"
                f"<b>NDVI:</b> {r['ndvi']}<br>"
                f"<b>NDRE:</b> {r['ndre']}<br>"
                f"<b>Vigor Z:</b> {vigor_z:.1f} &nbsp;|&nbsp; <b>Heterog.:</b> {het:.0f}/100<br>"
                f"<span style='font-size:0.8em;color:#94a3b8;'>Confidence: {conf:.0%}</span>"
                f"</div>",
                max_width=300,
            ),
        ).add_to(m)

    map_html = m._repr_html_()
    st_html(map_html, width=None, height=500)
