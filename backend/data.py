import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from backend.parcels import load_parcels
from backend.risk import compute_risk_scores, compute_peer_baselines

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

_rng = np.random.default_rng(42)

CROP_BASE_NDVI = {
    "Winter Wheat": 0.75, "Spring Wheat": 0.70, "Barley": 0.65,
    "Rapeseed": 0.68, "Maize": 0.60, "Oats": 0.66, "Rye": 0.62,
    "Potato": 0.82, "Sugar Beet": 0.80, "Ley / Grass": 0.55,
    "Fallow": 0.30, "Peas": 0.50,
}
CROP_BASE_NDRE = {
    "Winter Wheat": 0.58, "Spring Wheat": 0.54, "Barley": 0.48,
    "Rapeseed": 0.52, "Maize": 0.42, "Oats": 0.50, "Rye": 0.46,
    "Potato": 0.62, "Sugar Beet": 0.60, "Ley / Grass": 0.38,
    "Fallow": 0.15, "Peas": 0.35,
}
def _crop_ndvi(p):
    base = CROP_BASE_NDVI.get(p["crop"], 0.60)
    val = base + float(_rng.normal(0, 0.03))
    return max(0.05, min(0.95, val))


def _crop_ndre(p):
    base = CROP_BASE_NDRE.get(p["crop"], 0.45)
    val = base + float(_rng.normal(0, 0.025))
    return max(0.02, min(0.90, val))


def generate_demo_ndvi(parcels):
    return [float(_crop_ndvi(p)) for p in parcels]


def generate_demo_ndre(parcels):
    return [float(_crop_ndre(p)) for p in parcels]


def generate_demo_slope(parcels):
    return [round(float(_rng.uniform(0.3, 5.5)), 1) for _ in parcels]


def generate_ndvi_timeseries(parcels, n_steps=12):
    dates = pd.date_range(end=datetime.today(), periods=n_steps, freq="14D")
    ts_data = {}
    for p in parcels:
        base = CROP_BASE_NDVI.get(p["crop"], 0.60)
        trend = np.linspace(base - 0.03, base + 0.04, n_steps)
        trend = trend + _rng.normal(0, 0.025, n_steps)
        trend = np.clip(trend, 0.05, 0.95)
        ts_data[p["id"]] = trend
    return pd.DataFrame(ts_data, index=dates)


def build_demo_data(parcels=None, lat=None, lon=None):
    global _rng
    if parcels is None:
        parcels = load_parcels()
    if lat is not None and lon is not None:
        seed = abs(hash(f"{lat:.2f}_{lon:.2f}")) % (2**31)
        _rng = np.random.default_rng(seed)
    ndvi = generate_demo_ndvi(parcels)
    ndre = generate_demo_ndre(parcels)
    slope = generate_demo_slope(parcels)
    ndvi_std = [round(float(_rng.uniform(0.02, 0.12)), 3) for _ in parcels]
    ndvi_count = [int(_rng.uniform(10, 80)) for _ in parcels]

    peer_bl = compute_peer_baselines(parcels, ndvi)

    risks = compute_risk_scores(
        parcels, ndvi, ndre, slope,
        ndvi_std_values=ndvi_std,
        ndvi_count_values=ndvi_count,
        peer_baselines=peer_bl,
    )
    ts = generate_ndvi_timeseries(parcels)
    return {
        "parcels": parcels,
        "ndvi": ndvi,
        "ndre": ndre,
        "slope": slope,
        "ndvi_std": ndvi_std,
        "risks": risks,
        "timeseries": ts,
    }
