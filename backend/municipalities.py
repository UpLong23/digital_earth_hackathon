"""Swedish municipality boundaries and parcel-to-municipality assignment."""

from pathlib import Path
import geopandas as pd
from shapely.ops import transform
from pyproj import Transformer

_MUNI_GDF_CACHE = None
MUNI_GEOJSON = Path(__file__).resolve().parent.parent / "assets" / "swedish_municipalities.geojson"


def _load_municipalities():
    global _MUNI_GDF_CACHE
    if _MUNI_GDF_CACHE is not None:
        return _MUNI_GDF_CACHE
    _MUNI_GDF_CACHE = pd.read_file(str(MUNI_GEOJSON))
    _MUNI_GDF_CACHE["_name"] = _MUNI_GDF_CACHE["kom_namn"].str.strip()
    return _MUNI_GDF_CACHE


def get_municipality_names():
    gdf = _load_municipalities()
    return sorted(gdf["_name"].unique())


def get_municipality_polygon(name):
    gdf = _load_municipalities()
    row = gdf[gdf["_name"] == name]
    if row.empty:
        return None
    return row.iloc[0].geometry


def get_municipality_bbox(name):
    poly = get_municipality_polygon(name)
    if poly is None:
        return None
    # (minx, miny, maxx, maxy) in EPSG:4326
    b = poly.bounds
    return {"west": b[0], "south": b[1], "east": b[2], "north": b[3]}


def get_municipality_center(name):
    poly = get_municipality_polygon(name)
    if poly is None:
        return None
    c = poly.centroid
    return float(c.y), float(c.x)


def get_municipality_polygon_3006(name):
    poly = get_municipality_polygon(name)
    if poly is None:
        return None
    t = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)
    return transform(t.transform, poly)
