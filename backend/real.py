import random
from datetime import date, timedelta
import pandas as pd
from config import CROP_N_DEMAND, RISK_WEIGHTS


def _seed_for(lat, lon, start_date, end_date):
    """Deterministic seed from location + date range so data changes per query."""
    raw = f"{lat:.1f}_{lon:.1f}_{start_date}_{end_date}"
    return abs(hash(raw)) % (2**31)


def _build_timeseries(parcels, ndvi_values, start_date, end_date):
    """Build a 10-point time series centered around the given NDVI values."""
    from datetime import date as dt_date
    start = dt_date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = dt_date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    total_days = (end - start).days or 120
    step = total_days // 9 or 1

    ts_data = {}
    dates_idx = []
    rng = random.Random(42)
    for week in range(10):
        d = start + timedelta(days=week * step)
        dates_idx.append(d)
        for i, p in enumerate(parcels):
            pid = p["id"]
            if pid not in ts_data:
                ts_data[pid] = []
            base_ndvi = ndvi_values[i] if ndvi_values[i] is not None else 0.5
            ts_data[pid].append(round(base_ndvi + rng.uniform(-0.08, 0.08), 4))

    return pd.DataFrame(ts_data, index=pd.DatetimeIndex(dates_idx))


def build_real_data(conn, parcels, lat, lon, buffer_deg, start_date, end_date):
    """Build risk data using the real connection (location-seeded synthetic).

    Falls back to location-seeded synthetic risk scores when satellite data
    has not been explicitly fetched. Use build_real_data_from_satellite() to
    get actual Copernicus satellite-derived values.

    Returns (data_dict, None) or (None, error_string).
    """
    try:
        today = date.today()
        ndvi_mean = 0.55 + (today.day % 10) * 0.02
        ndre_mean = 0.25 + (today.day % 7) * 0.015
        slope_mean = 2.5 + (today.day % 4) * 0.3

        rng = random.Random(_seed_for(lat, lon, start_date, end_date))

        risks = []
        for p in parcels:
            parcel_id = p["id"] if "id" in p else str(parcels.index(p))
            crop = p.get("crop", "Unknown")

            base_demand = CROP_N_DEMAND.get(crop, CROP_N_DEMAND["Unknown"])
            n_uptake_score = min(100, max(0, (1 - base_demand) * 100))

            runoff_score = min(100, (slope_mean / 15) * 100)

            spreading_detected = ndvi_mean < 0.25 and ndre_mean < 0.10
            spreading_score = 80 if spreading_detected else 20

            crop_factor = (1 - base_demand) * 100

            w = RISK_WEIGHTS
            raw = (
                w["n_uptake"] * n_uptake_score
                + w["runoff"] * runoff_score
                + w["spreading"] * spreading_score
                + w["crop_factor"] * crop_factor
            )

            high_count = sum(
                [
                    n_uptake_score > 60,
                    runoff_score > 60,
                    spreading_score > 60,
                    crop_factor > 60,
                ]
            )
            synergy = 1.0 + (high_count - 1) * 0.15 if high_count > 1 else 1.0
            risk_score = min(100, raw * synergy)

            per_parcel_noise = rng.uniform(-0.03, 0.03)

            risks.append(
                {
                    "parcel_id": parcel_id,
                    "risk_score": round(float(risk_score), 1),
                    "ndvi": round(float(ndvi_mean + per_parcel_noise), 4),
                    "ndre": round(float(ndre_mean + per_parcel_noise * 0.5), 4),
                }
            )

        ndvi_vals = [r["ndvi"] for r in risks]
        ts_df = _build_timeseries(parcels, ndvi_vals, start_date, end_date)

        slopes = [round(slope_mean + rng.uniform(-0.5, 0.5), 1) for _ in risks]
        spreadings = [False for _ in risks]

        return {
            "risks": risks,
            "timeseries": ts_df,
            "slope": slopes,
            "spreading": spreadings,
        }, None
    except Exception as e:
        return None, f"Risk computation failed: {e}"


def _parcel_bbox(parcels):
    """Compute a bounding box from a list of parcel dicts (EPSG:4326)."""
    xs, ys = [], []
    for p in parcels:
        coords = p["geometry"]["coordinates"][0]
        xs.extend(c[0] for c in coords)
        ys.extend(c[1] for c in coords)
    return {
        "west": min(xs), "south": min(ys),
        "east": max(xs), "north": max(ys),
    }


def build_real_data_from_satellite(conn, parcels, lat, lon,
                                    start_date, end_date,
                                    progress_callback=None):
    """Build risk data using real Copernicus satellite imagery.

    Downloads Sentinel-2 NDVI/NDRE and Copernicus DEM via openEO,
    computes per-parcel zonal statistics, then feeds into the risk engine.

    When *parcels* span a large area (e.g. an entire municipality) the
    bounding box is derived from the parcel geometries instead of using
    the small fixed box around (lat, lon).

    Returns (data_dict, None) or (None, error_string).
    """
    try:
        if progress_callback:
            progress_callback(0.05, "Starting satellite fetch...")

        # Use parcel extent when it's larger than the default 0.15° box
        bbox = _parcel_bbox(parcels)

        from backend.satellite import fetch_satellite_data
        stats = fetch_satellite_data(
            conn, parcels, lat, lon, start_date, end_date,
            progress_callback=progress_callback,
            bbox=bbox,
        )

        ndvi_values = [s.get("ndvi") or 0.45 for s in stats]
        ndre_values = [s.get("ndre") or 0.20 for s in stats]
        ndti_values = [s.get("ndti") or 0.0 for s in stats]
        bsi_values = [s.get("bsi") or 0.0 for s in stats]
        ndmi_values = [s.get("ndmi") or 0.2 for s in stats]
        vh_vv_values = [s.get("vh_vv") or 0.25 for s in stats]
        slope_values = [s.get("slope") or 2.0 for s in stats]
        spreading_flags = [0 for _ in stats]

        from backend.risk import compute_risk_scores
        risks = compute_risk_scores(
            parcels, ndvi_values, ndre_values, spreading_flags, slope_values,
            ndti_values=ndti_values, bsi_values=bsi_values,
            ndmi_values=ndmi_values, vh_vv_values=vh_vv_values,
        )

        ts_df = _build_timeseries(parcels, ndvi_values, start_date, end_date)

        return {
            "risks": risks,
            "timeseries": ts_df,
            "ndti": ndti_values,
            "bsi": bsi_values,
            "ndmi": ndmi_values,
            "vh_vv": vh_vv_values,
            "slope": slope_values,
            "spreading": [False for _ in stats],
        }, None
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"Satellite data fetch failed: {e}"
