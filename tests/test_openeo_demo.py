import unittest


class FakeCapabilities:
    def api_version(self):
        return "1.2.0"


class FakeCollectionCube:
    def __init__(self, bands):
        self.bands = bands
        self.band_calls = []

    def band(self, name):
        self.band_calls.append(name)
        return FakeBand(name)


class FakeBand:
    def __init__(self, name):
        self.name = name

    def __sub__(self, other):
        return FakeExpression("subtract", self, other)

    def __add__(self, other):
        return FakeExpression("add", self, other)


class FakeExpression:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __truediv__(self, other):
        return FakeExpression("divide", self, other)

    def save_result(self, format):
        return {"format": format, "expression": self}


class FakeConnection:
    def __init__(self):
        self.loaded = []

    def capabilities(self):
        return FakeCapabilities()

    def list_collection_ids(self):
        return ["SENTINEL2_L2A", "SENTINEL2_L1C", "COPERNICUS_30"]

    def describe_collection(self, collection_id):
        return {
            "id": collection_id,
            "title": "Sentinel-2 L2A",
            "description": "Optical imagery.",
            "cube:dimensions": {
                "bands": {
                    "type": "bands",
                    "values": ["B04", "B08", "SCL"],
                }
            },
        }

    def load_collection(self, *args, **kwargs):
        self.loaded.append((args, kwargs))
        return FakeCollectionCube(kwargs["bands"])


class OpenEoDemoTests(unittest.TestCase):
    def test_summarize_backend_returns_api_version_and_collection_preview(self):
        from openeo_demo import summarize_backend

        summary = summarize_backend(FakeConnection(), max_collections=2)

        self.assertEqual(summary["api_version"], "1.2.0")
        self.assertEqual(summary["collection_count"], 3)
        self.assertEqual(summary["collection_preview"], ["SENTINEL2_L2A", "SENTINEL2_L1C"])

    def test_describe_collection_extracts_bands_from_cube_dimensions(self):
        from openeo_demo import describe_collection

        summary = describe_collection(FakeConnection(), "SENTINEL2_L2A")

        self.assertEqual(summary["id"], "SENTINEL2_L2A")
        self.assertEqual(summary["title"], "Sentinel-2 L2A")
        self.assertEqual(summary["bands"], ["B04", "B08", "SCL"])

    def test_build_sentinel2_ndvi_cube_loads_expected_collection_and_bands(self):
        from openeo_demo import build_sentinel2_ndvi_cube

        connection = FakeConnection()
        spatial_extent = {"west": 12.45, "south": 55.55, "east": 12.65, "north": 55.75}
        temporal_extent = ["2025-06-01", "2025-06-10"]

        result = build_sentinel2_ndvi_cube(
            connection,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            max_cloud_cover=20,
        )

        args, kwargs = connection.loaded[0]
        self.assertEqual(args, ("SENTINEL2_L2A",))
        self.assertEqual(kwargs["spatial_extent"], spatial_extent)
        self.assertEqual(kwargs["temporal_extent"], temporal_extent)
        self.assertEqual(kwargs["bands"], ["B04", "B08"])
        self.assertEqual(kwargs["max_cloud_cover"], 20)
        self.assertEqual(result["format"], "GTiff")


if __name__ == "__main__":
    unittest.main()
