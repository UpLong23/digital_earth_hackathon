OPENEO_BACKEND = "https://openeo.dataspace.copernicus.eu"

DEFAULT_LAT, DEFAULT_LON = 62.0, 15.0
DEFAULT_BUFFER_DEG = 0.04

CROP_N_DEMAND = {
    "Winter Wheat": 0.85,
    "Spring Wheat": 0.80,
    "Barley": 0.70,
    "Rapeseed": 0.65,
    "Maize": 0.75,
    "Oats": 0.60,
    "Rye": 0.65,
    "Potato": 0.90,
    "Sugar Beet": 0.85,
    "Ley / Grass": 0.40,
    "Fallow": 0.10,
    "Peas": 0.30,
    "Unknown": 0.50,
}

RISK_WEIGHTS = {
    "n_uptake": 0.44,
    "runoff": 0.36,
    "anomaly": 0.20,
}

WOFOST_ENABLED_DEFAULT = True
WOFOST_CACHE_TTL = 3600
SEASON_START_DEFAULT = "2025-04-01"
SEASON_END_DEFAULT = "2025-09-30"
