import tempfile, os, time
from pathlib import Path
from requests.exceptions import RequestException

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from pyproj import Transformer

SAT_CACHE_DIR = Path(tempfile.gettempdir()) / "godslingkollen_cache"
SAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

RESAMPLE_RES = 20
MAX_CLOUD_COVER = 30


def _bbox_from_latlon(lat: float, lon: float, size_deg: float = 0.15):
    return {
        "west": lon - size_deg,
        "east": lon + size_deg,
        "south": lat - size_deg,
        "north": lat + size_deg,
    }


def _retry(fn, *args, max_retries=3, base_wait=3, label="operation", **kwargs):
    """Retry *fn* with exponential backoff on transient errors.

    Retries on ConnectionError, Timeout, and any 5xx HTTP errors.
    """
    import requests
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except (ConnectionError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            if attempt == max_retries - 1:
                raise
            wait = base_wait * (2 ** attempt)
            print(f"  ⚠ {label} attempt {attempt + 1}/{max_retries} failed ({exc}), retrying in {wait}s...")
            time.sleep(wait)
        except Exception as exc:
            msg = str(exc)
            if "502" in msg or "503" in msg or "504" in msg or "Bad Gateway" in msg or "Service Unavailable" in msg:
                if attempt == max_retries - 1:
                    raise
                wait = base_wait * (2 ** attempt)
                print(f"  ⚠ {label} attempt {attempt + 1}/{max_retries} failed ({exc}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Exhausted retries for {label}")


def _submit_batch_job(conn, process, label, progress_callback, pct_pos):
    """Submit an openEO batch job and return the job object (already started)."""
    if progress_callback:
        progress_callback(pct_pos, f"Queuing {label}...")
    job = _retry(conn.create_job, process, title=f"Gödslingskollen {label}",
                 label=f"create job {label}")
    _retry(job.start, label=f"start job {label}")
    return job


def _wait_for_job(job, label, output_path, progress_callback,
                  pct_start, pct_end):
    """Poll a batch job until finished, then download result."""
    pct_mid = pct_start + (pct_end - pct_start) * 0.6
    states = {"created": 0.1, "queued": 0.2, "running": 0.6}
    while True:
        status = _retry(job.status, label=f"status check {label}")
        if status in states:
            pct = pct_start + states[status] * (pct_mid - pct_start)
            if progress_callback:
                progress_callback(pct, f"{label}: {status}")
            time.sleep(5)
        elif status == "finished":
            if progress_callback:
                progress_callback(pct_end, f"Downloading {label}...")
            _retry(job.download_result, output_path,
                   label=f"download {label}")
            if progress_callback:
                progress_callback(pct_end, f"{label} done")
            return
        else:
            raise RuntimeError(
                f"openEO job {label} failed with status {status}: {job.status()}"
            )


def _make_s2_process(conn, bbox, start, end):
    """Build the openEO process for S2 composite at 20 m — NDVI + NDRE only.

    Extra indices (NDTI, BSI, NDMI) were removed because they were unused
    in the final risk model.  S2 NDVI/NDRE are used directly for n-uptake risk and anomaly.
    """
    from openeo.processes import mean as openeo_mean

    s2 = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=bbox,
        temporal_extent=[start, end],
        bands=["B04", "B05", "B08"],
        max_cloud_cover=MAX_CLOUD_COVER,
    ).resample_spatial(resolution=RESAMPLE_RES)

    b04, b05, b08 = s2.band("B04"), s2.band("B05"), s2.band("B08")
    ndvi = (b08 - b04) / (b08 + b04 + 0.001)
    ndre = (b08 - b05) / (b08 + b05 + 0.001)

    return ndvi.merge_cubes(ndre).reduce_dimension(dimension="t", reducer=openeo_mean)


def download_s2(conn, bbox, start, end, output_path, progress_callback=None):
    """Download S2 multi-index GeoTIFF via batch job (20 m, ≤30 % cloud)."""
    process = _make_s2_process(conn, bbox, start, end)
    _download_with_progress_legacy(
        conn, process, output_path, progress_callback,
        "Sentinel-2 indices", pct_start=0.05, pct_end=0.40,
    )
    return output_path


def _download_with_progress_legacy(conn, process, output_path, progress_callback,
                                   label, pct_start=0.05, pct_end=0.4):
    """Legacy helper: submit, start, poll, download."""
    if progress_callback:
        progress_callback(pct_start, f"Creating batch job: {label}")
    job = conn.create_job(process, title=f"Gödslingskollen {label}")
    job.start()
    _wait_for_job(job, label, output_path, progress_callback, pct_start, pct_end)


def submit_s2_job(conn, bbox, start, end, progress_callback=None):
    """Submit S2 batch job for parallel execution.  Returns the job object."""
    process = _make_s2_process(conn, bbox, start, end)
    return _submit_batch_job(conn, process, "Sentinel-2 indices",
                             progress_callback, 0.05)


def download_dem(conn, bbox, output_path, progress_callback=None):
    """Download Copernicus DEM at native resolution (synchronous)."""
    if progress_callback:
        progress_callback(0.52, "Downloading digital elevation model...")
    dem = conn.load_collection("COPERNICUS_30", spatial_extent=bbox)
    dem_band = dem.band("DEM")
    _retry(dem_band.download, output_path, format="GTiff",
           label="DEM download")
    if progress_callback:
        progress_callback(0.60, "DEM done")


def _reproject_dem_to_utm(dem_path, s2_crs):
    with rasterio.open(dem_path) as src_dem:
        if str(src_dem.crs) == str(s2_crs):
            return src_dem

        transform, width, height = calculate_default_transform(
            src_dem.crs, s2_crs, src_dem.width, src_dem.height, *src_dem.bounds
        )
        profile = src_dem.profile.copy()
        profile.update(crs=s2_crs, transform=transform, width=width, height=height)
        dem_utm_path = SAT_CACHE_DIR / "dem_utm.tiff"
        with rasterio.open(dem_utm_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src_dem, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src_dem.transform,
                src_crs=src_dem.crs,
                dst_transform=transform,
                dst_crs=s2_crs,
                resampling=Resampling.bilinear,
            )
        return rasterio.open(dem_utm_path)


def compute_zonal_stats(parcels: list, s2_path: str,
                        dem_path: str,
                        progress_callback=None) -> list:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)

    with rasterio.open(s2_path) as src:
        s2_crs = src.crs
        arrs = {
            "ndvi": src.read(1),
            "ndre": src.read(2),
        }

    dem_src = _reproject_dem_to_utm(dem_path, s2_crs)
    dem = dem_src.read(1).astype(np.float64)
    dem = np.where(dem < -1000, np.nan, dem)
    dem = np.nan_to_num(dem, nan=np.nanmean(dem))
    res = abs(dem_src.transform[0])
    dx, dy = np.gradient(dem, res, res)
    slope_arr = np.degrees(np.arctan(np.sqrt(dx ** 2 + dy ** 2)))
    slope_arr = np.clip(slope_arr, 0, 90).astype(np.float32)
    dem_src.close()

    slope_path = SAT_CACHE_DIR / "slope_utm.tiff"
    with rasterio.open(s2_path) as ref:
        profile = ref.profile.copy()
    profile.update(dtype="float32", count=1)
    with rasterio.open(slope_path, "w", **profile) as dst:
        dst.write(slope_arr, 1)

    results = []
    n_parcels = len(parcels)
    with rasterio.open(s2_path) as src_s2, rasterio.open(slope_path) as src_slp:
        for idx, p in enumerate(parcels):
            if progress_callback and idx % max(1, n_parcels // 20) == 0:
                pct = 0.65 + (idx / n_parcels) * 0.32
                progress_callback(pct, f"Zonal stats: {idx}/{n_parcels} parcels")

            coords_utm = [transformer.transform(lon, lat) for lon, lat in
                          p["geometry"]["coordinates"][0]]
            geom = {"type": "Polygon", "coordinates": [coords_utm]}

            row = {"parcel_id": p["id"]}

            try:
                out, _ = mask(src_s2, [geom], crop=True, all_touched=True)
                for j, key in enumerate(["ndvi", "ndre"]):
                    vals = out[j][~np.isnan(out[j])]
                    if len(vals) > 0:
                        row[key] = float(vals.mean())
                        row[f"{key}_std"] = float(vals.std())
                        row[f"{key}_count"] = int(len(vals))
                    else:
                        row[key] = None
                        row[f"{key}_std"] = None
                        row[f"{key}_count"] = 0
            except Exception:
                for key in ["ndvi", "ndre"]:
                    row[key] = None
                    row[f"{key}_std"] = None
                    row[f"{key}_count"] = 0

            try:
                out, _ = mask(src_slp, [geom], crop=True, all_touched=True)
                vals = out[0].flatten()
                valid = vals[vals >= 0]
                row["slope"] = float(valid.mean()) if len(valid) > 0 else None
            except Exception:
                row["slope"] = None

            results.append(row)

    return results


def fetch_satellite_data(conn, parcels: list, lat: float, lon: float,
                         start: str, end: str,
                         progress_callback=None,
                         bbox: dict | None = None,
                         s2_job=None) -> list:
    """Orchestrate satellite data fetch with parallel execution.

    Accepts optional pre-submitted *s2_job* so the caller
    can start the batch job before calling this function (letting it
    run on the server while DEM downloads synchronously).
    """
    if bbox is None:
        bbox = _bbox_from_latlon(lat, lon)
    cache_key = f"{bbox['west']}_{bbox['south']}_{bbox['east']}_{bbox['north']}"
    s2_path = str(SAT_CACHE_DIR / f"s2_{cache_key}_{start}_{end}.tiff")
    dem_path = str(SAT_CACHE_DIR / f"dem_{cache_key}.tiff")

    s2_was_cached = os.path.exists(s2_path)
    if not s2_was_cached and s2_job is None:
        process = _make_s2_process(conn, bbox, start, end)
        s2_job = _submit_batch_job(conn, process, "Sentinel-2 indices",
                                   progress_callback, 0.05)

    if not os.path.exists(dem_path):
        download_dem(conn, bbox, dem_path, progress_callback=progress_callback)
    elif progress_callback:
        progress_callback(0.60, "DEM already cached")

    if not s2_was_cached and s2_job is not None:
        _wait_for_job(s2_job, "Sentinel-2 indices", s2_path,
                      progress_callback, 0.05, 0.60)
    elif progress_callback:
        progress_callback(0.60, "Sentinel-2 indices already cached")

    if progress_callback:
        progress_callback(0.65, "Computing per-parcel statistics...")

    stats = compute_zonal_stats(parcels, s2_path, dem_path,
                                progress_callback=progress_callback)

    if progress_callback:
        progress_callback(1.0, "Done!")

    return stats
