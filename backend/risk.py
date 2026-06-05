import statistics
from typing import Optional

import pandas as pd


def compute_peer_baselines(parcels, ndvi_values, ndvi_std_values=None):
    """Compute same-crop peer-group statistics (median, MAD) per crop type.

    Returns a dict: {crop: {"median": float, "mad": float, "n": int}}
    """
    groups = {}
    for i, p in enumerate(parcels):
        ndvi = ndvi_values[i] if ndvi_values and ndvi_values[i] is not None else None
        if ndvi is None:
            continue
        crop = p.get("crop", "Unknown")
        groups.setdefault(crop, []).append(ndvi)
        
    baselines = {}
    for crop, vals in groups.items():
        if len(vals) < 3:
            baselines[crop] = {"median": None, "mad": None, "n": len(vals)}
            continue
        med = statistics.median(vals)
        abs_devs = [abs(v - med) for v in vals]
        mad = statistics.median(abs_devs) if abs_devs else 0.1
        baselines[crop] = {"median": med, "mad": max(mad, 0.01), "n": len(vals)}
    return baselines


def compute_risk_scores(parcels, ndvi_values=None, ndre_values=None,
                         slope_values=None,
                         ndvi_std_values=None, ndvi_data_frac_values=None,
                         peer_baselines=None):
    """Multi-component risk scoring.

    Components:
      - Optical vigor anomaly (peer-relative z-score)
      - Within-field heterogeneity (ndvi_std)
      - Red-edge anomaly (NDRE deviation from crop median)
      - Runoff (slope)
      - Confidence (based on valid pixel fraction)
    """
    if peer_baselines is None:
        peer_baselines = {}

    results = []
    for i, p in enumerate(parcels):
        ndvi = float(ndvi_values[i]) if ndvi_values and ndvi_values[i] is not None else None
        ndre = float(ndre_values[i]) if ndre_values and ndre_values[i] is not None else None
        slope = float(slope_values[i]) if slope_values and slope_values[i] is not None else 0.0
        ndvi_std = float(ndvi_std_values[i]) if ndvi_std_values and ndvi_std_values[i] is not None else None
        ndvi_data_frac = float(ndvi_data_frac_values[i]) if ndvi_data_frac_values and ndvi_data_frac_values[i] is not None else 0.0

        crop = p.get("crop", "Unknown")
        bl = peer_baselines.get(crop, {})

        # ── Component 1: Peer-relative z-score ──────────────────────
        if ndvi is not None and bl.get("median") is not None and bl["n"] >= 3:
            vigor_z = (ndvi - bl["median"]) / bl["mad"]
        else:
            vigor_z = 0.0
        # Scale z to 0-100 for the risk formula (z=0→0, z=4→100)
        vigor_contrib = max(0.0, vigor_z / 4.0 * 100.0)

        # ── Component 2: Within-field heterogeneity ─────────────────
        ndvi_std_score = 0.0
        if ndvi_std is not None and ndvi is not None and ndvi > 0.2:
            cv = ndvi_std / max(ndvi, 0.01)
            ndvi_std_score = min(100.0, cv * 150.0)

        # ── Component 3: Red-edge anomaly ───────────────────────────
        ndre_diff = 0.0
        if ndre is not None and ndvi is not None:
            ratio = ndre / max(ndvi, 0.01)
            ndre_diff = min(100.0, max(0.0, (ratio - 0.5) * 200.0))

        # ── Component 4: Runoff ─────────────────────────────────────
        runoff_score = _runoff_risk(slope)

        # ── Confidence: fraction of valid pixels within parcel mask ─
        confidence = ndvi_data_frac

        # ── Equal-weighted average ─────────────────────────────────
        total = (vigor_contrib + ndvi_std_score + ndre_diff + runoff_score) / 4.0
        total = max(0.0, min(100.0, total))

        results.append({
            "parcel_id": str(p["id"]),
            "crop": crop,
            "risk_score": float(round(total, 1)),
            "vigor_z": float(round(vigor_z, 2)),
            "runoff_score": float(round(runoff_score, 1)),
            "heterogeneity_score": float(round(ndvi_std_score, 1)),
            "ndre_anomaly": float(round(ndre_diff, 1)),
            "confidence": float(round(confidence, 2)),
            "ndvi": float(round(ndvi, 3)) if ndvi is not None else None,
            "ndre": float(round(ndre, 3)) if ndre is not None else None,
            "ndvi_std": float(round(ndvi_std, 3)) if ndvi_std is not None else None,
        })
    return results


def _runoff_risk(slope_pct):
    if slope_pct <= 0.5:
        return 5.0
    if slope_pct <= 2.0:
        return 15.0
    if slope_pct <= 5.0:
        return 40.0
    if slope_pct <= 10.0:
        return 70.0
    return 95.0


def risk_label(score):
    if score < 30:
        return "Low", "#22c55e"
    if score < 60:
        return "Moderate", "#eab308"
    if score < 80:
        return "High", "#f97316"
    return "Critical", "#ef4444"


def compute_combined_risk(parcel_df: pd.DataFrame,
                          wofost_results: Optional[list] = None,
                          nutrient_results: Optional[list] = None,
                          use_wofost: bool = True) -> pd.DataFrame:
    """Combine heuristic and WOFOST-informed risk into a single per-parcel result.

    If WOFOST results are available and use_wofost is True, the
    overfertilization risk score from the nutrient assessment replaces
    the heuristic risk score. All original columns are preserved, and
    WOFOST columns are prefixed with 'wofost_' / 'nutrient_'.
    """
    df = parcel_df.copy()

    if use_wofost and wofost_results and nutrient_results:
        for i, (w_r, n_r) in enumerate(zip(wofost_results, nutrient_results)):
            if i >= len(df):
                break
            df.at[i, "risk_score"] = n_r.get("overfertilization_risk_score",
                                              df.at[i, "risk_score"])
            for key, val in w_r.items():
                if key in ("daily",):
                    continue
                df.at[i, f"wofost_{key}"] = val
            for key, val in n_r.items():
                df.at[i, f"nutrient_{key}"] = val
            lbl, _ = risk_label(df.at[i, "risk_score"])
            df.at[i, "risk_level"] = lbl

    return df
