import sys
import io
import re
import threading
from pathlib import Path
from config import OPENEO_BACKEND

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def connect_ee():
    """Connect to Copernicus Data Space via openEO OIDC.

    Always runs `authenticate_oidc()` in a daemon thread so the UI
    never blocks.  If a stored refresh token exists the thread
    finishes instantly → status "ready".  Otherwise the device-code
    URL printed to stdout is captured and returned → status
    "device_code".

    Returns dict: {"status": "ready"|"device_code"|"error",
                   "conn": connection_or_None,
                   "url": "device_code_url_or_None",
                   "message": "human_readable_message"}
    """
    import openeo
    conn = openeo.connect(OPENEO_BACKEND)

    result = {"success": False, "url": None, "error": None}
    buf = io.StringIO()

    def _auth():
        old = sys.stdout
        sys.stdout = buf
        try:
            conn.authenticate_oidc()
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
        finally:
            sys.stdout = old

    t = threading.Thread(target=_auth, daemon=True)
    t.start()
    t.join(timeout=3)

    if result["success"]:
        return {"status": "ready", "conn": conn, "url": None, "message": "Authenticated"}

    # Extract device-code URL from captured stdout
    output = buf.getvalue()
    for line in output.splitlines():
        if "http" in line.lower():
            m = re.search(r'(https?://\S+)', line)
            if m:
                result["url"] = m.group(0).rstrip(".")
                break

    if result["url"]:
        return {
            "status": "device_code",
            "conn": conn,
            "url": result["url"],
            "message": "Open the URL in your browser to authenticate.",
        }
    if result["error"]:
        return {"status": "error", "conn": conn, "url": None, "message": result["error"]}
    if t.is_alive():
        return {
            "status": "device_code",
            "conn": conn,
            "url": None,
            "message": "Timed out capturing URL. Run this in your terminal:\n"
                       "  uv run python -c \"import openeo; "
                       "openeo.connect('https://openeo.dataspace.copernicus.eu')"
                       ".authenticate_oidc(store_refresh_token=True)\"",
        }
    return {"status": "error", "conn": conn, "url": None, "message": "Unknown auth failure"}


def verify_connection(conn):
    """Verify the connection is working."""
    try:
        info = conn.describe_account()
        return True, info.get("user_id", "Connected")
    except Exception:
        try:
            caps = conn.capabilities()
            return True, caps.get("title", caps.get("backend_id", "Connected"))
        except Exception as e:
            return False, str(e)


def fetch_s2_ndvi(conn, lat, lon, buffer_deg, start_date, end_date, max_cloud=30):
    spat_extent = {
        "west": lon - buffer_deg, "south": lat - buffer_deg,
        "east": lon + buffer_deg, "north": lat + buffer_deg,
    }
    s2 = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=spat_extent,
        temporal_extent=[start_date, end_date],
        bands=["B04", "B08"],
        max_cloud_cover=max_cloud,
    )
    b04 = s2.band("B04")
    b08 = s2.band("B08")
    ndvi = (b08 - b04) / (b08 + b04 + 0.001)
    return ndvi


def fetch_s2_ndre(conn, lat, lon, buffer_deg, start_date, end_date, max_cloud=30):
    spat_extent = {
        "west": lon - buffer_deg, "south": lat - buffer_deg,
        "east": lon + buffer_deg, "north": lat + buffer_deg,
    }
    s2 = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=spat_extent,
        temporal_extent=[start_date, end_date],
        bands=["B06", "B08"],
        max_cloud_cover=max_cloud,
    )
    b06 = s2.band("B06")
    b08 = s2.band("B08")
    ndre = (b08 - b06) / (b08 + b06 + 0.001)
    return ndre


def fetch_s1_change(conn, lat, lon, buffer_deg, start_date, end_date):
    spat_extent = {
        "west": lon - buffer_deg, "south": lat - buffer_deg,
        "east": lon + buffer_deg, "north": lat + buffer_deg,
    }
    s1 = conn.load_collection(
        "SENTINEL1_GRD",
        spatial_extent=spat_extent,
        temporal_extent=[start_date, end_date],
        bands=["VV", "VH"],
    )
    return s1


def fetch_dtm(conn, lat, lon, buffer_deg):
    spat_extent = {
        "west": lon - buffer_deg, "south": lat - buffer_deg,
        "east": lon + buffer_deg, "north": lat + buffer_deg,
    }
    dtm = conn.load_collection("EU_DTM", spatial_extent=spat_extent)
    return dtm


def execute_and_download(cube, filepath):
    """Execute an openEO job and download the result as NetCDF."""
    job = cube.create_job(
        title="Gödslingskollen",
        description="Overfertilization risk analysis",
        process={"output_format": "netcdf"},
    )
    job.start_and_wait()
    job.download_results(filepath)
    return filepath
