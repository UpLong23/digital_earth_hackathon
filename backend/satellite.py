import tempfile, os, time, json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from pyproj import Transformer

SAT_CACHE_DIR = Path(tempfile.gettempdir()) / "godslingkollen_cache"
SAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _bbox_from_latlon(lat: float, lon: float, size_deg: float = 0.15):
    return {
        "west": lon - size_deg,
        "east": lon + size_deg,
        "south": lat - size_deg,
        "north": lat + size_deg,
    }


def _download_with_progress(conn, process, output_path, progress_callback,
                            label, pct_start=0.05, pct_end=0.4):
    """Submit an openEO batch job, poll with visible progress."""
    if progress_callback:
        progress_callback(pct_start, f"Creating batch job: {label}")

    job = conn.create_job(process, title=f"Gödslingskollen {label}")
    job.start()

    pct_range = pct_end - pct_start
    states = {"created": 0.1, "queued": 0.2, "running": 0.6}
    while True:
        status = job.status()
        if status in states:
            pct = pct_start + states[status] * pct_range
            if progress_callback:
                progress_callback(pct, f"{label}: {status}")
            time.sleep(5)
        elif status == "finished":
            if progress_callback:
                progress_callback(pct_end, f"Downloading {label}...")
            job.download_result(output_path)
            if progress_callback:
                progress_callback(pct_end, f"{label} done")
            return
        else:
            raise RuntimeError(f"openEO job {label} failed with status {status}: {job.status()}")


def download_s2(conn, bbox: dict, start: str, end: str, output_path: str,
                progress_callback=None) -> str:
    """Download multi-index S2 composite (NDVI, NDRE, NDTI, BSI, NDMI)."""
    from openeo.processes import mean as openeo_mean

    s2 = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=bbox,
        temporal_extent=[start, end],
        bands=["B02", "B03", "B04", "B05", "B08", "B11", "B12"],
        max_cloud_cover=60,
    )
    b02, b03, b04, b05, b08, b11, b12 = (
        s2.band("B02"), s2.band("B03"), s2.band("B04"),
        s2.band("B05"), s2.band("B08"), s2.band("B11"), s2.band("B12"),
    )
    ndvi = (b08 - b04) / (b08 + b04 + 0.001)
    ndre = (b08 - b05) / (b08 + b05 + 0.001)
    ndti = (b11 - b12) / (b11 + b12 + 0.001)
    bsi = ((b11 + b04) - (b08 + b02)) / ((b11 + b04) + (b08 + b02) + 0.001)
    ndmi = (b08 - b11) / (b08 + b11 + 0.001)

    combined = ndvi.merge_cubes(ndre).merge_cubes(ndti).merge_cubes(bsi).merge_cubes(ndmi)
    combined_mean = combined.reduce_dimension(dimension="t", reducer=openeo_mean)

    _download_with_progress(
        conn, combined_mean, output_path,
        progress_callback, "Sentinel-2 indices",
        pct_start=0.05, pct_end=0.4,
    )
    return output_path


def download_s1(conn, bbox: dict, start: str, end: str, output_path: str,
                progress_callback=None) -> str:
    """Download Sentinel-1 VV, VH, and VH/VV ratio."""
    from openeo.processes import mean as openeo_mean

    s1 = conn.load_collection(
        "SENTINEL1_GRD",
        spatial_extent=bbox,
        temporal_extent=[start, end],
        bands=["VV", "VH"],
    )
    s1_cal = s1.sar_backscatter()
    vv = s1_cal.band("VV")
    vh = s1_cal.band("VH")
    vh_vv = vh / (vv + 0.001)
    combined = vv.merge_cubes(vh).merge_cubes(vh_vv)
    s1_mean = combined.reduce_dimension(dimension="t", reducer=openeo_mean)

    _download_with_progress(
        conn, s1_mean, output_path,
        progress_callback, "Sentinel-1 SAR",
        pct_start=0.42, pct_end=0.55,
    )
    return output_path


def download_dem(conn, bbox: dict, output_path: str) -> str:
    dem = conn.load_collection("COPERNICUS_30", spatial_extent=bbox)
    dem_band = dem.band("DEM")
    dem_band.download(output_path, format="GTiff")
    return output_path


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


def compute_zonal_stats(parcels: list, s2_path: str, s1_path: str | None,
                        dem_path: str,
                        progress_callback=None) -> list:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)

    with rasterio.open(s2_path) as src:
        s2_crs = src.crs
        shape = (src.height, src.width)
        arrs = {
            "ndvi": src.read(1),
            "ndre": src.read(2),
            "ndti": src.read(3),
            "bsi": src.read(4),
            "ndmi": src.read(5),
        }

    s1_arrs = {}
    if s1_path and os.path.exists(s1_path):
        with rasterio.open(s1_path) as src:
            s1_arrs["vv"] = src.read(1)
            s1_arrs["vh"] = src.read(2)
            s1_arrs["vh_vv"] = src.read(3)

    dem_src = _reproject_dem_to_utm(dem_path, s2_crs)
    dem = dem_src.read(1).astype(np.float64)
    dem = np.where(dem < -1000, np.nan, dem)
    dem = np.nan_to_num(dem, nan=np.nanmean(dem))
    res = abs(dem_src.transform[0])
    dx, dy = np.gradient(dem, res, res)
    slope_arr = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
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
        s1_src = rasterio.open(s1_path) if s1_path and os.path.exists(s1_path) else None

        for idx, p in enumerate(parcels):
            if progress_callback and idx % max(1, n_parcels // 20) == 0:
                pct = 0.7 + (idx / n_parcels) * 0.28
                progress_callback(pct, f"Zonal stats: {idx}/{n_parcels} parcels")

            coords_utm = [transformer.transform(lon, lat) for lon, lat in
                          p["geometry"]["coordinates"][0]]
            geom = {"type": "Polygon", "coordinates": [coords_utm]}

            row = {"parcel_id": p["id"]}

            try:
                out, _ = mask(src_s2, [geom], crop=True, all_touched=True)
                for j, key in enumerate(["ndvi", "ndre", "ndti", "bsi", "ndmi"]):
                    vals = out[j][~np.isnan(out[j])]
                    row[key] = float(vals.mean()) if len(vals) > 0 else None
            except Exception:
                for key in ["ndvi", "ndre", "ndti", "bsi", "ndmi"]:
                    row[key] = None

            if s1_src:
                try:
                    out, _ = mask(s1_src, [geom], crop=True, all_touched=True)
                    for j, key in enumerate(["vv", "vh", "vh_vv"]):
                        vals = out[j][~np.isnan(out[j])]
                        row[key] = float(vals.mean()) if len(vals) > 0 else None
                except Exception:
                    for key in ["vv", "vh", "vh_vv"]:
                        row[key] = None

            try:
                out, _ = mask(src_slp, [geom], crop=True, all_touched=True)
                vals = out[0].flatten()
                valid = vals[vals >= 0]
                row["slope"] = float(valid.mean()) if len(valid) > 0 else None
            except Exception:
                row["slope"] = None

            results.append(row)

        if s1_src:
            s1_src.close()

    return results


def fetch_satellite_data(conn, parcels: list, lat: float, lon: float,
                         start: str, end: str,
                         progress_callback=None,
                         bbox: dict | None = None) -> list:
    if bbox is None:
        bbox = _bbox_from_latlon(lat, lon)
    cache_key = f"{bbox['west']}_{bbox['south']}_{bbox['east']}_{bbox['north']}"
    s2_path = str(SAT_CACHE_DIR / f"s2_{cache_key}_{start}_{end}.tiff")
    s1_path = str(SAT_CACHE_DIR / f"s1_{cache_key}_{start}_{end}.tiff")
    dem_path = str(SAT_CACHE_DIR / f"dem_{cache_key}.tiff")

    if not os.path.exists(s2_path):
        download_s2(conn, bbox, start, end, s2_path, progress_callback=progress_callback)
    else:
        if progress_callback:
            progress_callback(0.4, "Sentinel-2 indices already cached")

    if not os.path.exists(s1_path):
        download_s1(conn, bbox, start, end, s1_path, progress_callback=progress_callback)
    else:
        if progress_callback:
            progress_callback(0.55, "Sentinel-1 already cached")

    if not os.path.exists(dem_path):
        if progress_callback:
            progress_callback(0.6, "Downloading digital elevation model...")
        download_dem(conn, bbox, dem_path)
    else:
        if progress_callback:
            progress_callback(0.65, "DEM already cached")

    if progress_callback:
        progress_callback(0.7, "Computing per-parcel statistics...")

    stats = compute_zonal_stats(parcels, s2_path, s1_path, dem_path,
                                progress_callback=progress_callback)

    if progress_callback:
        progress_callback(1.0, "Done!")

    return stats
