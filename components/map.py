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
        tiles="CartoDB positron",
        attr="CartoDB",
    )

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
        overlay=False,
        control=True,
    ).add_to(m)

    if municipality and municipality != "Custom location":
        poly = get_municipality_polygon(municipality)
        if poly is not None:
            coords = [[c[1], c[0]] for c in poly.exterior.coords]
            folium.Polygon(
                locations=coords,
                color="#5a7d3c",
                weight=2.5,
                fill=False,
                dash_array="8, 4",
                popup=folium.Popup(
                    f"<b>Municipality:</b> {municipality}", max_width=200
                ),
            ).add_to(m)
            west, south, east, north = poly.bounds
            m.fit_bounds([[south, west], [north, east]])

    parcel_group = folium.FeatureGroup(name="Parcels", show=True)
    for p, r in zip(parcels, risks):
        label, color = risk_label(r["risk_score"])
        coords = p["geometry"]["coordinates"][0]
        polygon_coords = [(c[1], c[0]) for c in coords]

        vigor_z = r.get("vigor_z", 0)
        het = r.get("heterogeneity_score", 0)
        conf = r.get("confidence", 0)

        wofost_fields = ""
        yield_est = r.get("wofost_yield_kg_ha")
        n_surplus = r.get("nutrient_n_surplus_kg_ha")
        n_level = r.get("nutrient_overfertilization_risk_level")
        if yield_est is not None:
            wofost_fields += (
                f"<b>WOFOST yield:</b> {yield_est:.0f} kg/ha<br>"
            )
        if n_surplus is not None:
            wofost_fields += (
                f"<b>N surplus:</b> {n_surplus:.0f} kg/ha"
                f" &nbsp;|&nbsp; <b>N risk:</b> {n_level}<br>"
            )
        resolved_crop = r.get("wofost_resolved_crop")
        if resolved_crop:
            wofost_fields += (
                f"<span style='font-size:0.8em;color:#6b7280;'>"
                f"WOFOST crop: {resolved_crop}</span><br>"
            )

        popup_html = (
            f"<div style='min-width:180px;'>"
            f"<b>Parcel:</b> {p['id']}<br>"
            f"<b>Crop:</b> {p['crop']}<br>"
            f"<b>Risk:</b> {r['risk_score']}/100 &mdash; {label}<br>"
            f"<b>NDVI:</b> {r['ndvi']}<br>"
            f"<b>NDRE:</b> {r['ndre']}<br>"
            f"<b>Vigor Z:</b> {vigor_z:.1f} &nbsp;|&nbsp; "
            f"<b>Heterog.:</b> {het:.0f}/100<br>"
            f"<span style='font-size:0.8em;color:#6b7280;'>"
            f"Confidence: {conf:.0%}</span><br>"
            f"{wofost_fields}"
            f"</div>"
        )

        folium.Polygon(
            locations=polygon_coords,
            color="#3d3229",
            weight=1.2,
            fill_color=color,
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(parcel_group)

    parcel_group.add_to(m)

    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    map_html = m._repr_html_()

    if municipality and municipality != "Custom location":
        map_var = m.get_name()
        script = f"""<script>
{map_var}.on('baselayerchange', function(e) {{
    {map_var}.eachLayer(function(layer) {{
        if (layer instanceof L.Polygon && layer.options.dashArray) {{
            layer.setStyle({{
                color: e.name === 'Satellite' ? '#ffffff' : '#5a7d3c'
            }});
        }}
    }});
}});
</script>"""
        map_html = map_html.replace("</body>", script + "</body>")

    st_html(map_html, width=None, height=500)
