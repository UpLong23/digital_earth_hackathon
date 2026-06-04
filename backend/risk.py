from config import CROP_N_DEMAND, RISK_WEIGHTS

OPTIMAL_NDVI = {
    "Winter Wheat": 0.75, "Spring Wheat": 0.70, "Barley": 0.65,
    "Rapeseed": 0.68, "Maize": 0.60, "Oats": 0.66, "Rye": 0.62,
    "Potato": 0.82, "Sugar Beet": 0.80, "Ley / Grass": 0.55,
    "Fallow": 0.30, "Peas": 0.50, "Unknown": 0.60,
}


def compute_risk_scores(parcels, ndvi_values=None, ndre_values=None,
                         spreading_flags=None, slope_values=None,
                         ndti_values=None, bsi_values=None,
                         ndmi_values=None, vh_vv_values=None):
    results = []
    for i, p in enumerate(parcels):
        ndvi = float(ndvi_values[i]) if ndvi_values and ndvi_values[i] is not None else None
        ndre = float(ndre_values[i]) if ndre_values and ndre_values[i] is not None else None
        spreading = int(spreading_flags[i]) if spreading_flags and spreading_flags[i] else 0
        slope = float(slope_values[i]) if slope_values and slope_values[i] is not None else 0.0
        ndti = float(ndti_values[i]) if ndti_values and ndti_values[i] is not None else None
        bsi = float(bsi_values[i]) if bsi_values and bsi_values[i] is not None else None
        ndmi = float(ndmi_values[i]) if ndmi_values and ndmi_values[i] is not None else None
        vh_vv = float(vh_vv_values[i]) if vh_vv_values and vh_vv_values[i] is not None else None

        n_uptake_score = _n_uptake_risk(ndvi, p["crop"])
        runoff_score = _runoff_risk(slope)
        bare_soil_score = _bare_soil_risk(ndti, bsi)
        spreading_score = _spreading_risk(spreading, vh_vv)
        crop_factor = CROP_N_DEMAND.get(p["crop"], 0.5)

        total = (
            RISK_WEIGHTS["n_uptake"] * n_uptake_score
            + RISK_WEIGHTS["runoff"] * runoff_score
            + RISK_WEIGHTS["bare_soil"] * bare_soil_score
            + RISK_WEIGHTS["spreading"] * spreading_score
            + RISK_WEIGHTS["crop_factor"] * 100.0 * (1.0 - crop_factor)
        )

        # Moisture amplifier: wet soil (high NDMI) increases leaching
        if ndmi is not None and ndmi > 0.2:
            total *= 1.0 + (ndmi - 0.2) * 0.5
        total = min(100.0, total)

        n_high = 0
        if n_uptake_score > 50:
            n_high += 1
        if runoff_score > 40:
            n_high += 1
        if bare_soil_score > 50:
            n_high += 1
        if spreading_score > 50:
            n_high += 1
        if 100.0 * (1.0 - crop_factor) > 50:
            n_high += 1
        if n_high >= 2:
            total *= (1.0 + 0.10 * n_high)

        total = max(0.0, min(100.0, total))

        results.append({
            "parcel_id": str(p["id"]),
            "crop": str(p["crop"]),
            "risk_score": float(round(total, 1)),
            "n_uptake_score": float(round(n_uptake_score, 1)),
            "runoff_score": float(round(runoff_score, 1)),
            "bare_soil_score": float(round(bare_soil_score, 1)),
            "spreading_flag": int(spreading > 0),
            "crop_factor": float(round(crop_factor, 2)),
            "ndvi": float(round(ndvi, 3)) if ndvi is not None else None,
            "ndre": float(round(ndre, 3)) if ndre is not None else None,
            "ndti": float(round(ndti, 3)) if ndti is not None else None,
            "bsi": float(round(bsi, 3)) if bsi is not None else None,
            "ndmi": float(round(ndmi, 3)) if ndmi is not None else None,
        })
    return results


def _n_uptake_risk(ndvi, crop):
    expected = OPTIMAL_NDVI.get(crop, 0.65)
    if ndvi is None:
        return 30.0
    deficit = max(0.0, expected - ndvi) / max(expected, 0.01)
    return min(100.0, deficit * 130)


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


def _bare_soil_risk(ndti, bsi):
    """High NDTI or BSI indicates bare soil -> elevated leaching risk."""
    if ndti is None and bsi is None:
        return 40.0
    score = 0.0
    count = 0
    if ndti is not None:
        score += max(0, (ndti + 0.5) / 0.8 * 100)
        count += 1
    if bsi is not None:
        score += max(0, (bsi + 0.3) / 0.6 * 100)
        count += 1
    return min(100.0, score / count)


def _spreading_risk(spreading_flag, vh_vv):
    """Manure/compost spreading flattens soil -> low VH/VV.  Combine with flag."""
    if spreading_flag:
        return 100.0
    if vh_vv is not None and vh_vv < 0.2:
        return 70.0
    return 0.0


def risk_label(score):
    if score < 30:
        return "Low", "#22c55e"
    if score < 60:
        return "Moderate", "#eab308"
    if score < 80:
        return "High", "#f97316"
    return "Critical", "#ef4444"
