import streamlit as st
from datetime import date, timedelta
from config import CROP_N_DEMAND, DEFAULT_LAT, DEFAULT_LON


def _municipality_names():
    from backend.municipalities import get_municipality_names
    return ["Custom location"] + get_municipality_names()


def render_sidebar():
    with st.sidebar:
        st.markdown(
            "<h3 style='color:#e2e8f0;'>🌾 Gödslingskollen</h3>"
            "<p style='color:#94a3b8;font-size:0.85rem;'>Övergödningsövervakning</p>",
            unsafe_allow_html=True,
        )

        st.divider()

        muni_options = _municipality_names()
        muni_default = st.session_state.get("selected_municipality", "Custom location")
        muni_idx = muni_options.index(muni_default) if muni_default in muni_options else 0
        selected_muni = st.selectbox("Municipality", muni_options, index=muni_idx,
                                     help="Show all parcels within a municipality. Select 'Custom location' to use lat/lon instead.")

        is_custom = selected_muni == "Custom location"

        col1, col2 = st.columns(2)
        with col1:
            lat_in = st.number_input("Latitude", value=DEFAULT_LAT, format="%.4f",
                                     key="lat_input", disabled=not is_custom)
        with col2:
            lon_in = st.number_input("Longitude", value=DEFAULT_LON, format="%.4f",
                                     key="lon_input", disabled=not is_custom)

        today = date.today()
        default_start = today - timedelta(days=120)
        start_date = st.date_input("Start date", default_start)
        end_date = st.date_input("End date", today)

        crop_options = ["All"] + sorted(CROP_N_DEMAND.keys())
        crop_type = st.selectbox("Crop type", crop_options)

        st.divider()
        st.markdown("**Analysis Mode**")
        use_demo = st.toggle("Use demo data (synthetic)", value=True)

        if not use_demo:
            st.markdown("**Satellite Data Source**")
            st.write("Copernicus Data Space — openEO OIDC")

            if not st.session_state.get("conn_ready"):
                auth_info = st.session_state.get("auth_info")

                if not auth_info:
                    if st.button("🔗 Connect", type="primary", use_container_width=True):
                        from backend.sentinel import connect_ee
                        result = connect_ee()
                        if result["status"] == "ready":
                            st.session_state.conn_ready = True
                            st.session_state.conn = result["conn"]
                            st.rerun()
                        else:
                            st.session_state.auth_info = result
                            st.rerun()

                if auth_info:
                    if auth_info["status"] == "device_code":
                        if auth_info.get("url"):
                            st.info("\U0001f510 Open this link in your browser to authenticate:")
                            url = auth_info["url"]
                            st.markdown(f"\U0001f449 [Click to authenticate]({url})")
                            st.code(url, language="url")
                            st.caption(
                                "After authenticating, come back and click **Verify** below."
                            )
                        else:
                            st.warning(auth_info["message"])
                    else:
                        st.error(auth_info["message"])

                    if st.button("✅ Verify", use_container_width=True):
                        from backend.sentinel import connect_ee
                        result = connect_ee()
                        if result["status"] == "ready":
                            st.session_state.conn_ready = True
                            st.session_state.conn = result["conn"]
                            st.session_state.auth_info = None
                            st.rerun()
                        else:
                            st.session_state.auth_info = result
                            st.rerun()

            if st.session_state.get("conn_ready"):
                st.success("✅ Connected")
                if st.session_state.get("satellite_source"):
                    st.caption("🛰️ Using real Copernicus satellite data")
                else:
                    if st.button("🛰️ Fetch real satellite data (~3 min)",
                                 use_container_width=True,
                                 help="Downloads Sentinel-2 NDVI/NDRE + DEM from Copernicus"):
                        st.session_state.fetch_satellite = True
                        st.rerun()
                if st.button("Disconnect", use_container_width=True):
                    st.session_state.conn_ready = False
                    st.session_state.pop("conn", None)
                    st.session_state.pop("auth_info", None)
                    st.session_state.pop("fetch_satellite", None)
                    st.session_state.pop("satellite_source", None)
                    st.rerun()

        st.divider()
        st.markdown("**Parcel Source**")
        from backend.lpis import is_cached
        if is_cached():
            st.caption("🗺️ National LPIS dataset loaded")
        else:
            st.caption("📡 Querying parcels live via WFS")
            if st.button("⬇ Download national LPIS (~340 MB)",
                         use_container_width=True,
                         help="One-time download, enables instant parcel loading for all Sweden"):
                st.session_state.download_lpis = True
                st.rerun()

        if st.session_state.pop("download_lpis", False):
            with st.spinner("Downloading national LPIS dataset... (~340 MB)"):
                from backend.lpis import download_national
                download_national()
                st.rerun()

        st.divider()
        st.markdown("**Risk Legend**")
        cols = st.columns(4)
        colors = ["#22c55e", "#eab308", "#f97316", "#ef4444"]
        labels = ["Low", "Moderate", "High", "Critical"]
        for col, c, lbl in zip(cols, colors, labels):
            col.markdown(
                f'<span style="display:inline-block;width:12px;height:12px;'
                f'background:{c};border-radius:50%;"></span>'
                f'<span style="color:#e2e8f0;font-size:0.8rem;"> {lbl}</span>',
                unsafe_allow_html=True,
            )

        st.divider()
        if st.button("🔄 Refresh Analysis", type="primary", use_container_width=True):
            for k in ["demo_data", "real_data", "satellite_source"]:
                st.session_state.pop(k, None)
            st.rerun()

        st.divider()
        st.caption("Data: Sentinel-1, Sentinel-2, EU-DTM via Copernicus Data Space")
        st.caption("Built for Digital Earth Sweden Hackathon 2026")

        st.session_state.selected_municipality = selected_muni

        return {
            "lat": lat_in,
            "lon": lon_in,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "crop_type": crop_type,
            "use_demo": use_demo,
            "municipality": selected_muni,
        }
