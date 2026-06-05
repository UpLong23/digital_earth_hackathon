import json, time
from urllib.request import urlopen, Request

from backend.cache import cache_get, cache_set

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

# Conservative default for Swedish agricultural mineral soils
DEFAULT_SOIL = {
    "clay": 0.25,
    "sand": 0.40,
    "silt": 0.35,
    "bulk_density": 1.4,
    "ph": 6.2,
    "available_water_capacity": 0.15,
    "soc": 1.5,
    "nitrogen": 0.15,
    "source": "default_swedish",
    "fallback": True,
}

SOILGRIDS_PROPERTIES = [
    "clay", "sand", "silt", "bulkdensity", "phh2o", "nitrogen", "soc",
]


def _round_coord(v, digits=2):
    return round(v, digits)


def _cache_key(lat, lon):
    return f"soil_{_round_coord(lat)}_{_round_coord(lon)}"


def _query_soilgrids(lat, lon, depth="0-5cm"):
    """Query SoilGrids REST API for soil properties at a location."""
    params = {
        "property": SOILGRIDS_PROPERTIES,
        "lat": lat,
        "lon": lon,
        "depth": depth,
        "value": "mean",
    }
    query = "&".join(
        f"{k}={v}" if not isinstance(v, list) else
        "&".join(f"{k}={x}" for x in v)
        for k, v in params.items()
    )
    url = f"{SOILGRIDS_URL}?{query}"
    req = Request(url, headers={"Accept": "application/json"})
    resp = json.loads(urlopen(req, timeout=20).read())
    return resp


def _parse_soilgrids_response(resp) -> dict:
    """Extract mean values from SoilGrids response."""
    props = resp.get("properties", {})
    layers = props.get("layers", [])
    result = {}
    for layer in layers:
        name = layer.get("name", "")
        depths = layer.get("depths", [])
        if depths:
            result[name] = depths[0].get("values", {}).get("mean")
    return result


def _to_wofost_soil(raw: dict) -> dict:
    """Convert SoilGrids properties to WOFOST-compatible soil parameters."""
    clay = (raw.get("clay") or 25) / 100.0
    sand = (raw.get("sand") or 40) / 100.0
    silt = (raw.get("silt") or 35) / 100.0
    bd = (raw.get("bulkdensity") or 1.4) / 1000.0  # kg/m3 -> g/cm3
    ph = raw.get("phh2o") or 6.2
    n = (raw.get("nitrogen") or 0.15) / 100.0  # mg/kg -> g/kg
    soc = (raw.get("soc") or 1.5) / 10.0  # g/kg -> %

    # WOFOST soil water parameters — crude approximations
    # Based on clay content
    if clay > 0.35:
        smw = 0.20  # wilting point
        smfc = 0.40  # field capacity
        s0 = 0.45  # saturation
    elif clay > 0.20:
        smw = 0.12
        smfc = 0.30
        s0 = 0.40
    elif clay > 0.10:
        smw = 0.08
        smfc = 0.24
        s0 = 0.38
    else:
        smw = 0.04
        smfc = 0.18
        s0 = 0.35

    awc = smfc - smw

    return {
        "clay": clay,
        "sand": sand,
        "silt": silt,
        "bulk_density": bd,
        "ph": ph,
        "soc": soc,
        "nitrogen": n,
        "available_water_capacity": awc,
        "smw": smw,
        "smfc": smfc,
        "s0": s0,
        "soil_water_curve": "clay_based_approximation",
        "source": "soilgrids",
        "fallback": False,
    }


def fetch_soil(lat: float, lon: float) -> dict:
    """Fetch soil properties from SoilGrids, return WOFOST-compatible dict.

    Falls back to conservative Swedish defaults on failure.
    """
    ck = _cache_key(lat, lon)
    cached = cache_get(ck, ttl_seconds=86400 * 7)
    if cached is not None:
        return cached

    try:
        resp = _query_soilgrids(lat, lon)
        raw = _parse_soilgrids_response(resp)
        soil = _to_wofost_soil(raw)
        cache_set(ck, soil)
        return soil
    except Exception:
        return dict(DEFAULT_SOIL)
