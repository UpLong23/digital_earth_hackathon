import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Typical N uptake per tonne of yield (kg N / t) for common crops
N_UPTAKE_PER_TONNE = {
    "winter wheat": 25, "spring wheat": 24, "barley": 22,
    "oats": 20, "rye": 22, "maize": 18, "oilseed rape": 35,
    "potato": 4, "sugar beet": 3, "peas": 0,  # legumes fix their own N
    "field bean": 0, "grass": 20, "fallow": 0,
}

# Typical N removal in harvested product (kg N / t)
N_REMOVAL_PER_TONNE = {
    "winter wheat": 20, "spring wheat": 19, "barley": 17,
    "oats": 16, "rye": 17, "maize": 15, "oilseed rape": 28,
    "potato": 3, "sugar beet": 2, "peas": 30,
    "field bean": 32, "grass": 15, "fallow": 0,
}

# Recommended N ranges for Swedish conditions (kg N/ha)
RECOMMENDED_N_RANGE = {
    "winter wheat": (140, 190),
    "spring wheat": (110, 160),
    "barley": (90, 140),
    "oats": (80, 120),
    "rye": (90, 130),
    "maize": (130, 180),
    "oilseed rape": (150, 200),
    "potato": (100, 150),
    "sugar beet": (100, 140),
    "peas": (0, 0),
    "field bean": (0, 0),
    "grass": (150, 250),
    "fallow": (0, 0),
}


def assess_overfertilization_risk(
    parcel_row: dict,
    wofost_result: dict,
    weather_summary: dict,
    soil_data: dict,
    observed_n_input_kg_ha: Optional[float] = None,
) -> dict:
    """Assess overfertilization risk using WOFOST outputs and parcel context.

    Args:
        parcel_row: Parcel dict with crop, area_ha, geometry, etc.
        wofost_result: Output from run_wofost_simulation().
        weather_summary: Dict with total_rain_mm, avg_temp, etc.
        soil_data: Soil properties dict from fetch_soil().
        observed_n_input_kg_ha: Optional known N application rate.

    Returns:
        dict with N indicators, risk score, explanation, recommendation.
    """
    crop = _normalize_crop(parcel_row.get("crop", "Unknown"))
    yield_kg_ha = wofost_result.get("yield_kg_ha", 0)
    yield_t_ha = yield_kg_ha / 1000.0

    # ── Nitrogen uptake estimate ──
    n_uptake_rate = 0
    for key, val in N_UPTAKE_PER_TONNE.items():
        if key in crop.lower():
            n_uptake_rate = val
            break
    n_uptake_est = yield_t_ha * n_uptake_rate

    # ── Nitrogen removal at harvest ──
    n_removal_rate = 0
    for key, val in N_REMOVAL_PER_TONNE.items():
        if key in crop.lower():
            n_removal_rate = val
            break
    n_removed_harvest = yield_t_ha * n_removal_rate

    # ── Nitrogen input ──
    if observed_n_input_kg_ha is not None:
        n_input = observed_n_input_kg_ha
    else:
        n_input = _estimate_n_input(crop, yield_t_ha)

    # ── Surplus and efficiency ──
    n_surplus = max(0, n_input - n_uptake_est)
    n_use_efficiency = n_uptake_est / max(n_input, 1)

    # ── Risk factors ──
    runoff_loss_risk = _runoff_loss_risk(parcel_row, weather_summary)
    leaching_risk = _leaching_risk(soil_data, weather_summary, n_surplus)
    water_limitation = wofost_result.get("water_use_indicators", {}).get(
        "water_deficit_mm", 0) > 100

    # Heuristic risk from parcel
    heuristic_risk = parcel_row.get("risk_score", 0)
    heterogeneity = parcel_row.get("heterogeneity_score", 0)
    ndre_anomaly = parcel_row.get("ndre_anomaly", 0)
    confidence = parcel_row.get("confidence", 0.5)

    # ── Composite overfertilization risk score (0-100) ──
    components = []

    # Surplus contribution
    if n_surplus < 20:
        surp_score = 0
    elif n_surplus < 60:
        surp_score = 30
    elif n_surplus < 120:
        surp_score = 60
    else:
        surp_score = 90
    components.append(surp_score)

    # Runoff interaction with surplus
    if n_surplus > 40 and runoff_loss_risk:
        components.append(70)
    else:
        components.append(runoff_loss_risk * 100)

    # Leaching interaction
    if n_surplus > 40 and leaching_risk:
        components.append(65)
    else:
        components.append(leaching_risk * 100)

    # Yield gap (low yield with high N suggests inefficiency)
    attainable = wofost_result.get("yield_kg_ha", 0) * 1.3
    yield_gap_ratio = yield_kg_ha / max(attainable, 1)
    if yield_gap_ratio < 0.5 and n_input > 80:
        components.append(60)
    else:
        components.append(0)

    # High heterogeneity + high heuristic risk
    if heterogeneity > 50 and heuristic_risk > 50:
        components.append(70)
    else:
        components.append(0)

    # Low confidence penalty
    if confidence < 0.4:
        components.append(30)
    else:
        components.append(0)

    # WOFOST nutrient limitation signal
    if wofost_result.get("nutrient_aware") and not wofost_result.get("fallback_flags"):
        components.append(10)  # NWLP already accounts for nutrients
    else:
        components.append(20)  # uncertainty premium

    overfertilization_risk_score = min(100, sum(components) / max(len(components), 1))

    # ── Risk level ──
    if overfertilization_risk_score < 30:
        level = "Low"
    elif overfertilization_risk_score < 60:
        level = "Moderate"
    elif overfertilization_risk_score < 80:
        level = "High"
    else:
        level = "Critical"

    # ── Explanation ──
    explanation_parts = []
    if n_surplus > 60:
        explanation_parts.append(f"N surplus of {n_surplus:.0f} kg/ha indicates excess nitrogen.")
    if runoff_loss_risk and n_surplus > 40:
        explanation_parts.append("High runoff potential combined with N surplus — surface loss risk.")
    if leaching_risk and n_surplus > 40:
        explanation_parts.append("Leaching conditions with N surplus — groundwater risk.")
    if yield_gap_ratio < 0.5 and n_input > 80:
        explanation_parts.append("Low yield response to N input — inefficiency signal.")
    if confidence < 0.4:
        explanation_parts.append("Low satellite confidence — results uncertain.")
    if not explanation_parts:
        explanation_parts.append("N balance appears reasonable.")

    # ── Recommended action ──
    if overfertilization_risk_score >= 60:
        recommended_action = "Reduce N application by 20-30% and consider split application."
    elif overfertilization_risk_score >= 30:
        recommended_action = "Monitor crop development; consider precision N application."
    else:
        recommended_action = "Current N management appears appropriate."

    return {
        "n_uptake_est_kg_ha": round(n_uptake_est, 1),
        "n_removed_harvest_kg_ha": round(n_removed_harvest, 1),
        "n_input_kg_ha": round(n_input, 1),
        "n_surplus_kg_ha": round(n_surplus, 1),
        "n_use_efficiency": round(n_use_efficiency, 2),
        "water_limitation_flag": water_limitation,
        "runoff_loss_risk_flag": bool(runoff_loss_risk),
        "leaching_risk_flag": bool(leaching_risk),
        "overfertilization_risk_score": round(overfertilization_risk_score, 1),
        "overfertilization_risk_level": level,
        "explanation": " ".join(explanation_parts),
        "recommended_action": recommended_action,
    }


def _normalize_crop(crop_label: str) -> str:
    return crop_label.strip().lower()


def _estimate_n_input(crop: str, yield_t_ha: float) -> float:
    for key, (lo, hi) in RECOMMENDED_N_RANGE.items():
        if key in crop:
            mid = (lo + hi) / 2
            if yield_t_ha > 7:
                return hi
            if yield_t_ha > 4:
                return mid
            return lo
    return 100.0


def _runoff_loss_risk(parcel_row: dict, weather: dict) -> float:
    """Return runoff loss risk as float 0-1."""
    runoff_score = parcel_row.get("runoff_score", 0)
    total_rain = weather.get("total_rain_mm", 0)
    runoff = min(1, runoff_score / 95.0)
    wetness = min(1, total_rain / 300.0)
    return runoff * wetness


def _leaching_risk(soil_data: dict, weather: dict, n_surplus: float) -> float:
    """Return leaching risk as float 0-1."""
    sand = soil_data.get("sand", 0.3)
    clay = soil_data.get("clay", 0.3)
    total_rain = weather.get("total_rain_mm", 0)
    sand_factor = min(1, sand / 0.5)
    rain_factor = min(1, total_rain / 400.0)
    surplus_factor = min(1, n_surplus / 100.0)
    return sand_factor * 0.4 + rain_factor * 0.3 + surplus_factor * 0.3


def default_n_input_for_crop(crop: str) -> Optional[float]:
    """Return recommended N input range for a crop."""
    for key, (lo, hi) in RECOMMENDED_N_RANGE.items():
        if key in crop.lower():
            return (lo + hi) / 2.0
    return None
