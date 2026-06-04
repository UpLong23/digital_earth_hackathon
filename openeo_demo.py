"""Small openEO helpers for the accompanying quickstart notebook."""

from __future__ import annotations

from typing import Any


DEFAULT_BACKEND_URL = "https://openeo.dataspace.copernicus.eu"
DEFAULT_SENTINEL2_COLLECTION = "SENTINEL2_L2A"


def connect_to_backend(url: str = DEFAULT_BACKEND_URL, authenticate: bool = False) -> Any:
    """Connect to an openEO backend, optionally starting OIDC authentication."""
    import openeo

    connection = openeo.connect(url)
    if authenticate:
        connection.authenticate_oidc()
    return connection


def summarize_backend(connection: Any, max_collections: int = 10) -> dict[str, Any]:
    """Return a compact summary of backend API version and collection ids."""
    collection_ids = list(connection.list_collection_ids())
    capabilities = connection.capabilities()
    api_version = capabilities.api_version
    if callable(api_version):
        api_version = api_version()

    return {
        "api_version": str(api_version),
        "collection_count": len(collection_ids),
        "collection_preview": collection_ids[:max_collections],
    }


def describe_collection(
    connection: Any,
    collection_id: str = DEFAULT_SENTINEL2_COLLECTION,
) -> dict[str, Any]:
    """Return notebook-sized collection metadata with band names extracted."""
    metadata = connection.describe_collection(collection_id)
    return {
        "id": metadata.get("id", collection_id),
        "title": metadata.get("title") or metadata.get("name"),
        "description": metadata.get("description", ""),
        "bands": _extract_band_names(metadata),
        "extent": metadata.get("extent"),
    }


def build_sentinel2_ndvi_cube(
    connection: Any,
    spatial_extent: dict[str, float],
    temporal_extent: list[str],
    max_cloud_cover: int = 30,
    collection_id: str = DEFAULT_SENTINEL2_COLLECTION,
    result_format: str = "GTiff",
) -> Any:
    """Build a Sentinel-2 NDVI result graph without submitting a backend job."""
    cube = connection.load_collection(
        collection_id,
        spatial_extent=spatial_extent,
        temporal_extent=temporal_extent,
        bands=["B04", "B08"],
        max_cloud_cover=max_cloud_cover,
    )

    red = cube.band("B04")
    nir = cube.band("B08")
    ndvi = (nir - red) / (nir + red)
    return ndvi.save_result(format=result_format)


def _extract_band_names(metadata: dict[str, Any]) -> list[str]:
    dimensions = metadata.get("cube:dimensions", {})
    for dimension in dimensions.values():
        if dimension.get("type") == "bands" and dimension.get("values"):
            return list(dimension["values"])

    bands = metadata.get("bands") or metadata.get("summaries", {}).get("eo:bands", [])
    names: list[str] = []
    for band in bands:
        if isinstance(band, str):
            names.append(band)
        elif isinstance(band, dict) and band.get("name"):
            names.append(band["name"])
    return names
