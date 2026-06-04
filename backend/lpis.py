"""Fetch real LPIS parcels from Jordbruksverket.

Sources (in priority order):
  1. Local GeoParquet cache (full Sweden, ~340 MB) — fastest once downloaded
  2. WFS live query (bbox filter) — no download needed, slower but always available

Run `uv run python -m backend.lpis download` to pre-cache the full national dataset.
"""

import json, os, tempfile, time
from pathlib import Path
from urllib.request import urlopen
from pyproj import Transformer

import requests

DATA_DIR = Path(tempfile.gettempdir()) / "godslingkollen_lpis"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PARQUET_PATH = DATA_DIR / "sweden.parquet"
PARQUET_SOURCE = "https://data.source.coop/fiboa/sweden/sweden.parquet"
INDEX_PATH = DATA_DIR / "index.geojson"  # simplified centers for fast bbox filtering

WFS_URL = "http://epub.sjv.se/inspire/inspire/ows"
WFS_LAYER = "inspire:senaste_arslager_skifte"

# ── Crop code mapping ──

CROP_CODE_TO_EN = {
    1: "Winter Barley", 2: "Spring Barley", 3: "Oats", 4: "Winter Wheat",
    5: "Spring Wheat", 6: "Legume Mix", 7: "Winter Triticale", 8: "Rye",
    9: "Maize", 10: "Buckwheat", 12: "Spring Mixed Grain", 13: "Grain-Legume Mix",
    14: "Canary Seed", 15: "Millet", 16: "Cereal Silage",
    20: "Winter Rapeseed", 21: "Spring Rapeseed", 24: "Sunflower",
    25: "Oilseed Trial", 30: "Peas", 31: "Peas (canning)", 32: "Field Beans",
    33: "Sweet Lupin", 34: "Protein Mix", 35: "Brown Beans",
    36: "Vetch", 39: "Soybean", 40: "Flax (oil)", 41: "Flax (fiber)",
    42: "Hemp", 43: "Beans (other)", 45: "Potato (table)", 46: "Potato (starch)",
    47: "Sugar Beet", 48: "Fodder Beet",
    49: "Ley / Grass (not organic)", 50: "Ley / Grass", 52: "Pasture",
    53: "Hay Meadow", 54: "Forest Pasture", 57: "Ley for Drying", 58: "Grass Seed (annual)",
    59: "Grass Seed (perennial)", 60: "Fallow", 62: "Clover Seed", 63: "Energy Grass",
    65: "Salix", 66: "Buffer Zone", 67: "Poplar", 68: "Hybrid Aspen",
    70: "Strawberries", 71: "Berries (other)", 72: "Orchard", 73: "Nut Orchard",
    74: "Vegetable Garden", 77: "Water Protection Zone", 78: "Nursery",
    80: "Green Fodder", 81: "Green Manure", 82: "Wetland",
    83: "Christmas Trees", 87: "Other Eligible",
    88: "Other Cultivation", 89: "Mosaic Pasture", 90: "Grass-poor Land",
    95: "Restoration Pasture",
    310: "Wildlife Field", 311: "Early Potato", 312: "Asparagus",
    313: "Rhubarb", 314: "Non-eligible Land",
    315: "Autumn Mixed Grain", 316: "Perennial Wheat", 317: "Perennial Rye",
    318: "Flowering Field Margin",
}

INTERNAL_CROP_MAP = {
    "Winter Wheat": ["Winter Wheat", "Perennial Wheat"],
    "Spring Wheat": ["Spring Wheat"],
    "Winter Barley": ["Winter Barley", "Winter Barley"],
    "Spring Barley": ["Spring Barley"],
    "Oats": ["Oats"],
    "Rye": ["Rye", "Winter Triticale", "Autumn Mixed Grain",
             "Spring Mixed Grain", "Grain-Legume Mix",
             "Buckwheat", "Canary Seed", "Millet", "Cereal Silage"],
    "Maize": ["Maize"],
    "Sugar Beet": ["Sugar Beet"],
    "Potato": ["Potato (table)", "Potato (starch)", "Early Potato"],
    "Rapeseed": ["Winter Rapeseed", "Spring Rapeseed",
                  "Sunflower", "Flax (oil)", "Flax (fiber)",
                  "Hemp", "Sweet Lupin", "Vetch", "Soybean", "Beans (other)"],
    "Peas": ["Peas", "Peas (canning)", "Field Beans", "Brown Beans",
              "Protein Mix", "Legume Mix"],
    "Ley / Grass": ["Ley / Grass", "Ley / Grass (not organic)", "Ley for Drying",
                     "Grass Seed (annual)", "Grass Seed (perennial)", "Green Fodder",
                     "Hay Meadow", "Mosaic Pasture", "Grass-poor Land",
                     "Restoration Pasture", "Clover Seed", "Energy Grass",
                     "Pasture", "Forest Pasture", "Green Manure"],
    "Fallow": ["Fallow", "Non-eligible Land", "Buffer Zone", "Wetland",
                "Wildlife Field", "Flowering Field Margin",
                "Water Protection Zone", "Other Eligible", "Other Cultivation",
                "Christmas Trees", "Nursery", "Salix", "Poplar", "Hybrid Aspen",
                "Perennial Wheat", "Perennial Rye"],
    "Unknown": [],
}


def _map_to_internal_crop(crop_en):
    for internal, names in INTERNAL_CROP_MAP.items():
        if crop_en in names:
            return internal
    return "Unknown"


SV_CROP_MAP = {
    "Vete (höst)": "Winter Wheat", "Vete (vår)": "Spring Wheat",
    "Korn (höst)": "Winter Barley", "Korn (vår)": "Spring Barley",
    "Havre": "Oats", "Råg": "Rye", "Majs": "Maize",
    "Sockerbetor": "Sugar Beet", "Matpotatis": "Potato",
    "Stärkelsepotatis": "Potato", "Färskpotatis": "Potato",
    "Raps (höst)": "Rapeseed", "Raps (vår)": "Rapeseed",
    "Ärter (ej konservärter)": "Peas", "Konservärter": "Peas",
    "Åkerbönor": "Peas", "Bruna bönor": "Peas",
    "Slåtter och betesvall på åkermark med  en vallgröda": "Ley / Grass",
    "Slåtter och betesvall på åkermark": "Ley / Grass",
    "Betesmark (ej åker)": "Ley / Grass",
    "Slåttervall på åker (kontrakt med vallfodertork, Grovfoder)": "Ley / Grass",
    "Slåtteräng (ej åker)": "Ley / Grass",
    "Grönfoder": "Ley / Grass", "Energigräs": "Ley / Grass",
    "Träda": "Fallow", "Skyddszon mot vattenområde": "Fallow",
    "Våtmark": "Fallow", "Viltåker": "Fallow",
    "Blommande åker och fältkant": "Fallow",
}


def _map_sv_crop(sv_name):
    for sv_key, internal in SV_CROP_MAP.items():
        if sv_name.startswith(sv_key):
            return internal
    return "Unknown"


def _transform_geometry(geom, transformer):
    if geom["type"] == "Polygon":
        new_coords = [
            [list(transformer.transform(x, y)) for x, y in ring]
            for ring in geom["coordinates"]
        ]
        return {"type": "Polygon", "coordinates": new_coords}
    elif geom["type"] == "MultiPolygon":
        new_coords = [
            [[list(transformer.transform(x, y)) for x, y in ring] for ring in poly]
            for poly in geom["coordinates"]
        ]
        return {"type": "MultiPolygon", "coordinates": new_coords}
    return geom


# ── National Parquet Cache ──

_gdf_cache = None  # module-level cache to avoid reloading


def is_cached() -> bool:
    return PARQUET_PATH.exists()


def _load_gdf():
    global _gdf_cache
    if _gdf_cache is not None:
        return _gdf_cache
    import geopandas as gpd
    _gdf_cache = gpd.read_parquet(PARQUET_PATH)
    return _gdf_cache


def clear_cache():
    global _gdf_cache
    _gdf_cache = None


def download_national(progress_callback=None):
    """Download the full Sweden LPIS parquet to local cache."""
    if is_cached():
        if progress_callback:
            progress_callback(1.0, "Already cached")
        return

    if progress_callback:
        progress_callback(0.0, "Downloading national LPIS dataset (~340 MB)...")

    resp = requests.get(PARQUET_SOURCE, stream=True, timeout=300)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 340_000_000))
    downloaded = 0
    chunk_size = 8192

    with open(PARQUET_PATH, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded / total, None)

    if progress_callback:
        progress_callback(1.0, "Download complete")


def get_parcels_from_cache(lat: float, lon: float, size_deg: float = 0.15,
                           max_features: int = 200) -> list:
    """Query parcels from the local GeoParquet cache.

    Filters by bounding box around (lat, lon), then converts to app format.
    Returns empty list if cache doesn't exist.
    """
    if not is_cached():
        return []

    from pyproj import Transformer

    # Transform bbox from EPSG:4326 to EPSG:3006 for fast filtering
    t_to_3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
    x1, y1 = t_to_3006.transform(lon - size_deg, lat - size_deg)
    x2, y2 = t_to_3006.transform(lon + size_deg, lat + size_deg)
    bbox_3006 = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    west_3006, south_3006, east_3006, north_3006 = bbox_3006

    gdf = _load_gdf()
    if gdf.empty:
        clear_cache()
        return []

    # Filter in native CRS (EPSG:3006) — faster than reprojecting first
    idx = gdf.sindex
    possible = list(idx.intersection(bbox_3006))
    if not possible:
        return []

    filtered = gdf.iloc[possible].cx[west_3006:east_3006, south_3006:north_3006]
    filtered = filtered.sort_values("area", ascending=False)
    filtered = filtered.head(max_features)

    # Convert to EPSG:4326
    if filtered.crs is None or str(filtered.crs) != "EPSG:4326":
        filtered = filtered.to_crs("EPSG:4326")

    parcels = []
    for _, row in filtered.iterrows():
        geom = row.geometry.__geo_interface__
        if row.geometry.geom_type == "MultiPolygon":
            polygons = sorted(row.geometry.geoms, key=lambda g: g.area, reverse=True)
            geom = polygons[0].__geo_interface__

        sv_name = str(row.get("crop_name", "")).strip()
        internal_crop = _map_sv_crop(sv_name)

        area_ha = float(row.get("area") or 1.0)
        pid = str(row.get("id", f"LPIS-{row.name}"))

        coords = geom["coordinates"][0]
        parcels.append({
            "id": f"LPIS-{pid}",
            "crop": internal_crop,
            "area_ha": area_ha,
            "geometry": geom,
            "municipality": "",
            "lat_center": float(sum(c[1] for c in coords) / len(coords)),
            "lon_center": float(sum(c[0] for c in coords) / len(coords)),
        })

    return parcels


# ── WFS Live Query (fallback) ──

def fetch_lpis_parcels(lat: float, lon: float, size_deg: float = 0.15,
                       max_features: int = 200) -> list:
    """Fetch real LPIS parcels near (lat, lon) via Jordbruksverket WFS.

    Tries local parquet cache first, then falls back to WFS.
    """
    if is_cached():
        cached = get_parcels_from_cache(lat, lon, size_deg, max_features)
        if cached:
            return cached

    # WFS fallback
    from owslib.wfs import WebFeatureService
    t_to_3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
    t_from_3006 = Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)

    x1, y1 = t_to_3006.transform(lon - size_deg, lat - size_deg)
    x2, y2 = t_to_3006.transform(lon + size_deg, lat + size_deg)
    bbox_3006 = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    wfs = WebFeatureService(WFS_URL, version="2.0.0")
    response = wfs.getfeature(
        typename=WFS_LAYER,
        bbox=bbox_3006,
        outputFormat="json",
        maxfeatures=max_features,
    )
    data = json.loads(response.read())

    parcels = []
    for i, f in enumerate(data.get("features", [])):
        props = f["properties"]
        geom_3006 = f["geometry"]
        crop_code = props.get("grdkod_mar")
        crop_en = CROP_CODE_TO_EN.get(crop_code, "Unknown")
        crop = _map_to_internal_crop(crop_en)
        area_ha = props.get("ansokt_areal_ha") or props.get("faststalld_areal_ha") or 1.0
        geom_4326 = _transform_geometry(geom_3006, t_from_3006)
        parcel_id = f'LPIS-{props.get("blockid", "????")}-{props.get("skiftesbeteckning", i)}'
        coords = geom_4326["coordinates"][0]
        parcels.append({
            "id": parcel_id,
            "crop": crop,
            "area_ha": float(area_ha),
            "geometry": geom_4326,
            "municipality": "",
            "lat_center": float(sum(c[1] for c in coords) / len(coords)),
            "lon_center": float(sum(c[0] for c in coords) / len(coords)),
        })

    return parcels


# ── Municipality Query ──


def get_parcels_in_municipality(muni_name: str,
                                max_features: int = 5000) -> list:
    """Get all LPIS parcels within a municipality boundary.

    Uses the national parquet cache. Returns up to *max_features* parcels
    sorted by area descending.
    """
    if not is_cached():
        return []

    from backend.municipalities import get_municipality_polygon_3006

    poly_3006 = get_municipality_polygon_3006(muni_name)
    if poly_3006 is None:
        return []

    bbox_3006 = poly_3006.bounds
    gdf = _load_gdf()
    if gdf.empty:
        return []

    idx = gdf.sindex
    possible = list(idx.intersection(bbox_3006))
    if not possible:
        return []

    filtered = gdf.iloc[possible]
    filtered = filtered[filtered.intersects(poly_3006)]
    filtered = filtered.sort_values("area", ascending=False)
    filtered = filtered.head(max_features)

    if filtered.crs is None or str(filtered.crs) != "EPSG:4326":
        filtered = filtered.to_crs("EPSG:4326")

    parcels = []

    for _, row in filtered.iterrows():
        geom = row.geometry.__geo_interface__
        if row.geometry.geom_type == "MultiPolygon":
            polys = sorted(row.geometry.geoms, key=lambda g: g.area, reverse=True)
            geom = polys[0].__geo_interface__

        sv_name = str(row.get("crop_name", "")).strip()
        internal_crop = _map_sv_crop(sv_name)

        area_ha = float(row.get("area") or 1.0)
        pid = str(row.get("id", f"LPIS-{row.name}"))
        coords = geom["coordinates"][0]

        parcels.append({
            "id": f"LPIS-{pid}",
            "crop": internal_crop,
            "area_ha": area_ha,
            "geometry": geom,
            "municipality": muni_name,
            "lat_center": float(sum(c[1] for c in coords) / len(coords)),
            "lon_center": float(sum(c[0] for c in coords) / len(coords)),
        })

    return parcels


# ── CLI ──

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "download":
        def progress(pct, msg):
            if msg:
                print(msg)
            elif pct < 1.0:
                print(f"  {pct*100:.0f}%", end="\r", flush=True)
        print("Downloading national LPIS dataset...")
        download_national(progress)
        print(f"\nDone! Cached to {PARQUET_PATH}")
    else:
        print(f"Usage: uv run python -m backend.lpis download")
        print(f"       Downloads ~340 MB GeoParquet of all Sweden crop fields")
