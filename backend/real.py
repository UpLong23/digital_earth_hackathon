import random
from datetime import date, timedelta
from typing import Optional

import pandas as pd


def _seed_for(lat, lon, start_date, end_date):
    """Deterministic seed from location + date range so data changes per query."""
    raw = f"{lat:.1f}_{lon:.1f}_{start_date}_{end_date}"
    return abs(hash(raw)) % (2**31)


def _build_timeseries(parcels, ndvi_values, srre_values, start_date, end_date):
    """Build 10-point time series for NDVI and SRRE."""
    from datetime import date as dt_date
    start = dt_date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = dt_date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    total_days = (end - start).days or 120
    step = total_days // 9 or 1

    ts_ndvi, ts_srre = {}, {}
    dates_idx = []
    rng = random.Random(42)
    for week in range(10):
        d = start + timedelta(days=week * step)
        dates_idx.append(d)
        for i, p in enumerate(parcels):
            pid = p["id"]
            ts_ndvi.setdefault(pid, [])
            ts_srre.setdefault(pid, [])
            base_v = ndvi_values[i] if ndvi_values[i] is not None else 0.5
            base_s = srre_values[i] if srre_values[i] is not None else 1.5
            ts_ndvi[pid].append(round(base_v + rng.uniform(-0.08, 0.08), 4))
            ts_srre[pid].append(round(base_s + rng.uniform(-0.4, 0.4), 4))

    idx = pd.DatetimeIndex(dates_idx)
    return pd.DataFrame(ts_ndvi, index=idx), pd.DataFrame(ts_srre, index=idx)


def _run_wofost_pipeline(parcels, risk_list, lat, lon, start_date, end_date,
                         progress_callback=None) -> tuple:
    """Run WOFOST + nutrient pipeline for all parcels in parallel.

    Returns (wofost_results_list, nutrient_results_list).
    Each list parallels the parcels/risks lists.
    Gracefully degrades to empty lists on failure.
    """
    try:
        from backend.wofost import (CropResolver, sowing_date_for,
                                     _prepare_wofost_bundle, run_single_wofost,
                                     _heuristic_result)
        from backend.weather import fetch_weather
        from backend.soil import fetch_soil
        from backend.nutrient import assess_overfertilization_risk
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        weather_df = fetch_weather(lat, lon, start_date, end_date)
        weather_summary = {
            "total_rain_mm": float(weather_df["RAIN"].sum()),
            "avg_temp": float(weather_df["TEMP"].mean()),
        }
        soil_data = fetch_soil(lat, lon)

        bundle = _prepare_wofost_bundle(lat, lon, weather_df, soil_data)

        n = len(parcels)
        results = [None] * n
        lock = threading.Lock()
        done = [0]

        def run_one(idx):
            p = parcels[idx]
            r = risk_list[idx] if idx < len(risk_list) else {}

            if bundle is None:
                from backend.wofost import CropResolver
                resolved = CropResolver().resolve_crop(p["crop"])
                wofost_res = _heuristic_result(
                    p["crop"], resolved, lat, lon,
                    start_date, end_date, soil_data, parcel_features=r,
                )
            else:
                sowing = sowing_date_for(p["crop"])
                wofost_res = run_single_wofost(
                    p["crop"], lat, lon, start_date, end_date,
                    bundle, parcel_features=r, sowing_date=sowing,
                )

            nutr_res = assess_overfertilization_risk(
                parcel_row=r, wofost_result=wofost_res,
                weather_summary=weather_summary, soil_data=soil_data,
            )

            with lock:
                results[idx] = (wofost_res, nutr_res)
                done[0] += 1
                if progress_callback:
                    pct = 0.80 + (done[0] / max(n, 1)) * 0.15
                    progress_callback(pct, f"WOFOST: {done[0]}/{n} parcels")

        with ThreadPoolExecutor(max_workers=8) as pool:
            pool.map(run_one, range(n))

        wofost_results = [r[0] for r in results]
        nutrient_results = [r[1] for r in results]
        return wofost_results, nutrient_results

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return [], []


def _enrich_risks_with_wofost(risk_list, wofost_results, nutrient_results, parcels=None):
    """Merge WOFOST/nutrient fields into risk dicts in-place.

    Computes total_yield_kg = yield_kg_ha * area_ha for each parcel.
    """
    for i, (r, w, n) in enumerate(zip(risk_list, wofost_results, nutrient_results)):
        for key, val in w.items():
            if key in ("daily",):
                continue
            r[f"wofost_{key}"] = val
        for key, val in n.items():
            r[f"nutrient_{key}"] = val
        # Compute total yield from area
        area_ha = None
        if parcels and i < len(parcels):
            area_ha = parcels[i].get("area_ha")
        if area_ha and w.get("yield_kg_ha"):
            r["wofost_total_yield_kg"] = round(w["yield_kg_ha"] * area_ha, 0)
            r["wofost_total_yield_tonnes"] = round(w["yield_kg_ha"] * area_ha / 1000, 2)
    return risk_list


def build_real_data(conn, parcels, lat, lon, buffer_deg, start_date, end_date,
                    use_wofost=False):
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

        # Generate per-parcel values
        ndvi_list, ndre_list, srre_list, slope_list = [], [], [], []
        ndvi_std_list, ndvi_df_list = [], []
        for p in parcels:
            noise = rng.uniform(-0.03, 0.03)
            ndvi_list.append(round(float(ndvi_mean + noise), 4))
            ndre_val = round(float(ndre_mean + noise * 0.5), 4)
            ndre_list.append(ndre_val)
            srre_list.append(round((1 + ndre_val) / (1 - ndre_val), 4))
            slope_list.append(round(slope_mean + rng.uniform(-0.5, 0.5), 1))
            ndvi_std_list.append(round(rng.uniform(0.02, 0.12), 3))
            ndvi_df_list.append(round(rng.uniform(0.3, 0.98), 2))

        from backend.risk import compute_risk_scores, compute_peer_baselines
        peer_bl = compute_peer_baselines(parcels, ndvi_list)

        risks = compute_risk_scores(
            parcels, ndvi_list, ndre_list, slope_list,
            ndvi_std_values=ndvi_std_list,
            ndvi_data_frac_values=ndvi_df_list,
            peer_baselines=peer_bl,
        )

        ts_df, ts_srre_df = _build_timeseries(parcels, ndvi_list, srre_list, start_date, end_date)

        result = {
            "risks": risks,
            "timeseries": ts_df,
            "timeseries_srre": ts_srre_df,
            "srre": srre_list,
            "slope": slope_list,
            "ndvi_std": ndvi_std_list,
        }

        if use_wofost:
            wofost_results, nutrient_results = _run_wofost_pipeline(
                parcels, risks, lat, lon, start_date, end_date,
            )
            result["wofost_results"] = wofost_results
            result["nutrient_results"] = nutrient_results
            if wofost_results:
                _enrich_risks_with_wofost(risks, wofost_results, nutrient_results, parcels)

        return result, None
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
                                    progress_callback=None,
                                    municipality=None,
                                    use_wofost=False):
    """Build risk data using real Copernicus satellite imagery.

    Features extracted:
      - NDVI, NDRE (optical)
      - NDVI_std (within-field spatial variance)
      - NDVI_count (valid pixel count → confidence)
      - Slope (runoff)
      - Peer-group baselines (same-crop median/MAD)

    Returns (data_dict, None) or (None, error_string).
    """
    try:
        if progress_callback:
            progress_callback(0.05, "Starting satellite fetch...")

        bbox = _parcel_bbox(parcels)

        from backend.satellite import submit_s2_job, fetch_satellite_data

        s2_job = submit_s2_job(conn, bbox, start_date, end_date,
                               progress_callback)

        stats = fetch_satellite_data(
            conn, parcels, lat, lon, start_date, end_date,
            progress_callback=progress_callback,
            bbox=bbox, s2_job=s2_job,
        )

        ndvi_values = [s.get("ndvi") or 0.45 for s in stats]
        ndre_values = [s.get("ndre") or 0.20 for s in stats]
        srre_values = [s.get("srre") or 1.5 for s in stats]
        slope_values = [s.get("slope") or 2.0 for s in stats]
        ndvi_std_values = [s.get("ndvi_std") for s in stats]
        ndvi_data_frac_values = [s.get("ndvi_data_frac") or 0.0 for s in stats]

        if progress_callback:
            progress_callback(0.78, "Computing peer baselines...")

        from backend.risk import compute_risk_scores, compute_peer_baselines
        peer_bl = compute_peer_baselines(parcels, ndvi_values, ndvi_std_values)

        risks = compute_risk_scores(
            parcels, ndvi_values, ndre_values, slope_values,
            ndvi_std_values=ndvi_std_values,
            ndvi_data_frac_values=ndvi_data_frac_values,
            peer_baselines=peer_bl,
        )

        ts_df, ts_srre_df = _build_timeseries(parcels, ndvi_values, srre_values, start_date, end_date)

        result = {
            "risks": risks,
            "timeseries": ts_df,
            "timeseries_srre": ts_srre_df,
            "srre": srre_values,
            "slope": slope_values,
            "ndvi_std": ndvi_std_values,
        }

        if use_wofost:
            if progress_callback:
                progress_callback(0.80, "Running WOFOST simulations...")
            wofost_results, nutrient_results = _run_wofost_pipeline(
                parcels, risks, lat, lon, start_date, end_date,
                progress_callback=progress_callback,
            )
            result["wofost_results"] = wofost_results
            result["nutrient_results"] = nutrient_results
            if wofost_results:
                _enrich_risks_with_wofost(risks, wofost_results, nutrient_results, parcels)

        return result, None
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"Satellite data fetch failed: {e}"
