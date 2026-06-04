import json
import random
import numpy as np
from pathlib import Path
from config import CROP_N_DEMAND

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

CROPS = sorted(CROP_N_DEMAND.keys())
SOIL_TYPES = ["Clay loam", "Sandy loam", "Clay", "Silt loam", "Peat", "Loamy sand", "Silty clay"]

# Build a rotation-safe pair list for crop_prev
_CROP_PREV_MAP = {}
for i, c in enumerate(CROPS):
    _CROP_PREV_MAP[c] = CROPS[(i + 1) % len(CROPS)]


def _generate_polygon(cx, cy, size_deg, rotation_deg):
    """Generate a roughly rectangular polygon around (cx, cy) with rotation."""
    hw = size_deg / 2
    rot = rotation_deg * np.pi / 180
    corners = [(-hw, -hw), (hw, -hw), (hw, hw), (-hw, hw), (-hw, -hw)]
    rotated = []
    for dx, dy in corners:
        rx = dx * np.cos(rot) - dy * np.sin(rot)
        ry = dx * np.sin(rot) + dy * np.cos(rot)
        rotated.append([round(cx + rx, 6), round(cy + ry, 6)])
    return {"type": "Polygon", "coordinates": [rotated]}


def generate_parcels(lat, lon, count=10):
    """Synthetically generate parcels around a given lat/lon."""
    rng = random.Random(abs(hash(f"{lat:.3f}_{lon:.3f}")) % (2**31))

    parcels = []
    used_positions = set()
    for i in range(count):
        grid_cols = max(3, int(np.ceil(count ** 0.5)))
        row = i // grid_cols
        col = i % grid_cols
        spacing = 0.015

        for attempt in range(20):
            dx = (col - grid_cols / 2) * spacing + rng.uniform(-0.003, 0.003)
            dy = (row - grid_cols / 2) * spacing + rng.uniform(-0.003, 0.003)
            key = (round(dx, 4), round(dy, 4))
            if key not in used_positions:
                used_positions.add(key)
                break

        px = lon + dx
        py = lat + dy
        size = rng.uniform(0.008, 0.018)
        rotation = rng.uniform(0, 90)
        geometry = _generate_polygon(px, py, size, rotation)

        crop = rng.choice(CROPS)
        crop_prev = _CROP_PREV_MAP[crop]
        area = round(rng.uniform(4, 20), 1)
        soil = rng.choice(SOIL_TYPES)

        pid = f"SYN-{i+1:03d}"

        properties = {
            "parcel_id": pid,
            "crop_2024": crop,
            "crop_2023": crop_prev,
            "area_ha": area,
            "soil_type": soil,
            "municipality": "",
        }
        parcels.append({
            "id": pid,
            "crop": crop,
            "crop_prev": crop_prev,
            "area_ha": area,
            "soil": soil,
            "lat_center": py,
            "lon_center": px,
            "geometry": geometry,
            "properties": properties,
        })
    return parcels


def load_parcels(geojson_path=None):
    if geojson_path is None:
        geojson_path = ASSETS_DIR / "sample_parcels.geojson"
    with open(geojson_path) as f:
        data = json.load(f)

    parcels = []
    for feat in data["features"]:
        props = feat["properties"]
        coords = feat["geometry"]["coordinates"][0]
        lon_center = np.mean([c[0] for c in coords])
        lat_center = np.mean([c[1] for c in coords])

        parcels.append({
            "id": props["parcel_id"],
            "crop": props["crop_2024"],
            "crop_prev": props["crop_2023"],
            "area_ha": props["area_ha"],
            "soil": props["soil_type"],
            "municipality": props["municipality"],
            "lat_center": lat_center,
            "lon_center": lon_center,
            "geometry": feat["geometry"],
            "properties": props,
        })
    return parcels


def filter_parcels(parcels, crop_type=None, municipality=None, max_parcels=None):
    filtered = list(parcels)
    if crop_type and crop_type != "All":
        filtered = [p for p in filtered if p["crop"] == crop_type]
    if municipality:
        filtered = [p for p in filtered if p["municipality"].lower() == municipality.lower()]
    if max_parcels:
        filtered = filtered[:max_parcels]
    return filtered


def parcels_to_geojson(parcels):
    features = []
    for p in parcels:
        features.append({
            "type": "Feature",
            "properties": p["properties"],
            "geometry": p["geometry"],
        })
    return {"type": "FeatureCollection", "features": features}
