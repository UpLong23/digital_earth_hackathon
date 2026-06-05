# Gödslingskollen — Technical Report

## Overview

**Gödslingskollen** ("The Fertilization Check") is a Streamlit dashboard that detects possible overfertilization on Swedish farmland. It scores each agricultural parcel 0–100 by comparing satellite-derived vegetation indices (NDVI, NDRE) against same-crop peer fields, within-field heterogeneity, and terrain-runoff potential. A WOFOST crop growth simulation (optional) adds yield, N-uptake, and N-surplus estimates, feeding into a composite overfertilization risk score.

The app was built for the **Digital Earth Sweden Hackathon 2026** and targets Swedish board of agriculture (Jordbruksverket) LPIS parcel data, Sentinel-2 satellite imagery via Copernicus Data Space (openEO), and the WOFOST crop model (PCSE v5.6+).

---

## Architecture Overview

```
main.py                    ← Streamlit entry point
├── .streamlit/config.toml  ← warm earth theme
├── components/
│   ├── sidebar.py          ← all controls (municipality, dates, demo/WOFOST toggles)
│   ├── map.py              ← Folium risk map (CartoDB + Esri Satellite)
│   └── timeseries.py       ← Plotly time series + WOFOST summary charts
├── backend/
│   ├── data.py             ← demo/synthetic data generator
│   ├── real.py             ← real-data orchestrator (satellite + WOFOST pipeline)
│   ├── satellite.py        ← openEO batch job (S2 NDVI/NDRE + DEM slope)
│   ├── lpis.py             ← LPIS parcel fetcher (GeoParquet cache → WFS fallback)
│   ├── parcels.py          ← synthetic parcel generator + filter
│   ├── risk.py             ← 4-component risk engine
│   ├── wofost.py           ← WOFOST model runner (CropResolver, batch, heuristic fallback)
│   ├── weather.py          ← Open-Meteo weather fetcher
│   ├── soil.py             ← SoilGrids soil fetcher
│   ├── nutrient.py         ← N-budget + overfertilization risk assessment
│   ├── cache.py            ← JSON file cache with TTL
│   └── municipalities.py   ← 290 Swedish municipality boundaries
├── assets/
│   ├── swedish_municipalities.geojson
│   └── sample_parcels.geojson
├── future_work.md
└── pyproject.toml
```

---

## Data Sources & Pipelines

### 1. LPIS Parcels (Jordbruksverket)

**Source**: [Source Cooperative GeoParquet](https://data.source.coop/fiboa/sweden/sweden.parquet) (~341 MB, all of Sweden, 1.14 M fields).

**Fallback**: WFS live query at `http://epub.sjv.se/inspire/inspire/ows`, layer `inspire:senaste_arslager_skifte`.

**Pipeline** (`backend/lpis.py`):
1. On first load, check if national GeoParquet is cached at `/tmp/godslingkollen_lpis/sweden.parquet`.
2. If cached, load with GeoPandas, filter by bounding box (EPSG:3006 native CRS for fast spatial index lookups) or municipality polygon intersection.
3. If not cached, query the WFS endpoint with a bbox in EPSG:3006, parse the JSON response.
4. For each parcel: convert geometry from EPSG:3006 → EPSG:4326, map crop code → English name → internal crop name (12 types).
5. MultiPolygons are split; only the largest polygon (by area) is kept per parcel.

**Crop mapping**: `CROP_CODE_TO_EN` maps 60+ SAM codes → English; `INTERNAL_CROP_MAP` maps English → one of 12 internal types (Winter Wheat, Spring Wheat, Barley, Oats, Rye, Maize, Sugar Beet, Potato, Rapeseed, Peas, Ley/Grass, Fallow, Unknown). Swedish names are also handled via `SV_CROP_MAP`.

**Municipality query** (`lpis.py:get_parcels_in_municipality`): Uses a municipality polygon (from `assets/swedish_municipalities.geojson`, EPSG:4326) transformed to EPSG:3006, then spatial-intersects with the LPIS GeoDataFrame. Up to 5000 parcels returned, sorted by area descending.

### 2. Sentinel-2 Satellite Imagery (Copernicus Data Space)

**Source**: openEO at `https://openeo.dataspace.copernicus.eu`.

**Pipeline** (`backend/satellite.py`):
1. **Authentication**: OIDC device-code flow via `openeo.connect().authenticate_oidc(store_refresh_token=True)`.
2. **S2 batch job**: Load `SENTINEL2_L2A` collection with bands B04 (red), B05 (red-edge), B08 (NIR). Spatial extent from parcel bbox; temporal from user date range; `max_cloud_cover=30%`; resample to 20m.
3. **Indices computed server-side**:
   - `NDVI = (B08 - B04) / (B08 + B04 + 0.001)`
   - `NDRE = (B08 - B05) / (B08 + B05 + 0.001)`
   - Merged via `merge_cubes`, reduced over time with `mean()`.
4. **SRRE derived locally**: `SRRE = (1 + NDRE) / (1 - NDRE)` — eliminates need for a 3rd openEO band.
5. **DEM**: Copernicus_30 (sync download), reprojected to UTM zone 33N, gradient computed for slope (`np.gradient` → `arctan`).
6. **Zonal stats** (`compute_zonal_stats`): Mask raster with parcel polygon using `rasterio.mask.mask`, compute mean NDVI/NDRE/NDVI_std/slope per parcel. Valid pixel fraction → confidence.

**Retry logic**: `_retry()` wraps job creation, start, status check, and download with exponential backoff (3 attempts, 3s/6s/12s) on connection errors and 5xx responses.

### 3. Weather (Open-Meteo)

**Source**: [Open-Meteo Archive API](https://archive-api.open-meteo.com/v1/archive) or Forecast API.

**Pipeline** (`backend/weather.py`):
1. Fetch daily `temperature_2m_max/min/mean`, `precipitation_sum`, `shortwave_radiation_sum`, `et0_fao_evapotranspiration`, `wind_speed_10m_max`, `relative_humidity_2m_mean`.
2. Convert to PCSE-compatible DataFrame: `IRRAD = shortwave_radiation_sum * 100` (MJ/m² → J/cm²), `VAP` from temperature + humidity via Magnus formula, `ET0` from open-meteo.
3. **Fallback**: Synthetic Swedish summer weather (sine-based seasonal temperature/radiation trends with noise).
4. Cached as JSON with 1h TTL.

### 4. Soil (SoilGrids)

**Source**: ISRIC SoilGrids REST API at `https://rest.isric.org/soilgrids/v2.0/properties/query`.

**Pipeline** (`backend/soil.py`):
1. Query 7 properties at depth 0–5 cm: clay, sand, silt, bulkdensity, phh2o, nitrogen, soc.
2. Parse mean values → WOFOST-compatible parameters:
   - Soil water params (SMW, SMFC, S0) approximated from clay content using hard-coded thresholds.
   - Available water capacity (AWC) = SMFC − SMW.
3. **Fallback**: Conservative Swedish mineral soil defaults (25% clay, 40% sand, 35% silt, bulk density 1.4, AWC 0.15).
4. Cached as JSON with 7-day TTL.

---

## Risk Score Engine

**File**: `backend/risk.py`

The risk score is a **four-component equal-weighted average**, each 0–100:

| Component | Description | Formula |
|-----------|-------------|---------|
| 1. Vigor anomaly (z-score) | How far a parcel's NDVI deviates from its crop peer group | `z = (NDVI - median) / MAD` → `vigor_contrib = min(z/4 × 100, 100)` |
| 2. Heterogeneity | Within-field spatial variability | `cv = NDVI_std / NDVI` → `min(cv × 150, 100)` (only if NDVI > 0.2) |
| 3. Red-edge anomaly | NDRE/NDVI ratio deviation | `ratio = NDRE / NDVI` → `min(max((ratio − 0.5) × 200, 0), 100)` |
| 4. Runoff | Terrain slope | Piecewise: ≤0.5% → 5, ≤2% → 15, ≤5% → 40, ≤10% → 70, >10% → 95 |

**Final**: `risk_score = (vigor_contrib + heterogeneity + ndre_diff + runoff) / 4`, clamped to [0, 100].

**Peer baselines**: `compute_peer_baselines()` computes same-crop median and MAD of NDVI across all parcels in the query set. Requires ≥3 parcels per crop; otherwise z = 0.

**Labels**: `<30` Low (green), `30–59` Moderate (yellow), `60–79` High (orange), `80+` Critical (red).

**Confidence**: Fraction of valid (non-NaN) pixels within parcel mask after S2 cloud masking.

---

## WOFOST Crop Growth Simulation

**File**: `backend/wofost.py`

**Model**: PCSE (Python Crop Simulation Environment) v5.6+. Auto-detects the best available model in order: `Wofost80_NWLP_FD_beta` → `Wofost80_WLP_FD_beta` → `Wofost72_WLP_FD`. NWLP (Nutrient + Water Limited Production) is preferred but usually falls back to WLP (Water Limited).

**Crop parameters**: Cloned from [`https://github.com/ajwdewit/WOFOST_crop_parameters`](https://github.com/ajwdewit/WOFOST_crop_parameters) (wofost72 branch, 23 crops) to `/tmp/WOFOST_crop_parameters/`. A pickle cache (`YAMLCropDataProvider.pkl`) speeds reloads.

**CropResolver** (`wofost.py:63`): Resolves Swedish LPIS labels to WOFOST crop/variety names. Matching cascade:
1. Exact match
2. Synonym lookup (`CROP_SYNONYMS`)
3. Seasonal qualifier removal (e.g., "spring" → match "spring wheat" ↔ "wheat")
4. Substring match
5. Fuzzy token overlap (Jaccard-like)
6. Fallback (return `crop: None` → heuristic)

**Variety selection**: Prefers winter/spring match from crop name → variety name; falls back to "default" or first variety.

**Single-parcel run** (`run_single_wofost`):
1. Thread-local `YAMLCropDataProvider` created (cheap after pickle cache).
2. `set_active_crop(yaml_crop_name, yaml_variety)`.
3. `ParameterProvider(sitedata, soildata, cropdata)` built.
4. Agro management as campaign list with crop calendar (sowing date, maturity end type).
5. `model_cls(params, weather_provider, agro_data)` created.
6. `run_till(min(season_end, weather_provider.last_date))`.
7. Output: `TWSO` (total weight storage organs) × 1000 → yield kg/ha, `TAGP` × 1000 → biomass, `LAI`, `TRA` (transpiration).

**Heuristic fallback** (`_heuristic_result`): When WOFOST fails or is unavailable, estimates yield from `CROP_BASE_YIELDS` dict (e.g., potato 35 t/ha, sugar beet 50 t/ha, wheat 6 t/ha), adjusted by latitude factor (`1.0 − (abs(lat) − 55) × 0.03`), season length factor (`days / 150`), and NDVI boost (×1.2 if NDVI > 0.7, ×0.5 if <0.3).

**Parallel batch** (`real.py:_run_wofost_pipeline`):
1. Fetch weather + soil once (shared across parcels).
2. `_prepare_wofost_bundle()` creates weather_provider, soil_params, and detects model class.
3. `ThreadPoolExecutor(max_workers=8)` runs `run_single_wofost` per parcel.
4. Each thread creates its own `YAMLCropDataProvider` (fast from pickle cache) to avoid PCSE Engine `set_active_crop()` conflicts.
5. Progress reported via lock-protected counter.

**Known limitation**: Current default TSUM1/TSUM2 parameters are calibrated for Dutch/continental climate — simulated yield at 62°N is typically 0 kg/ha due to insufficient growing-degree-days. Swedish-calibrated parameters are needed (see `future_work.md`).

---

## Nutrient Assessment

**File**: `backend/nutrient.py`

**Purpose**: Combine WOFOST output + satellite features + weather + soil into an N-surplus estimate and overfertilization risk score.

**N budget**:
- `n_input`: user-provided value or auto-estimated from `RECOMMENDED_N_RANGE` × yield level.
- `n_uptake_est = yield_t_ha × N_UPTAKE_PER_TONNE[crop]`
- `n_removed = yield_t_ha × N_REMOVAL_PER_TONNE[crop]`
- `n_surplus = max(0, n_input − n_uptake_est)`

**Overfertilization risk score** (composite, 0–100):
Components averaged:
- Surplus contribution: piecewise thresholds (0/30/60/90).
- Runoff×surplus interaction.
- Leaching×surplus interaction.
- Yield gap (low yield with high N → inefficiency).
- High heterogeneity + high heuristic risk.
- Low confidence penalty.
- WOFOST nutrient-awareness premium.

**Risk level**: Same thresholds as optical risk (<30 Low, 30–59 Moderate, 60–79 High, ≥80 Critical).

**Recommendation**: Auto-generated text (e.g., "Reduce N application by 20-30%...") based on score.

---

## Streamlit Dashboard

### Entry Point (`main.py`)

**Flow**:
1. `render_sidebar()` collects all filters (municipality/latlon, date range, crop filter, demo toggle, WOFOST/nutrient toggles, N input, sowing date override).
2. Hash-based query cache busting — re-runs only when filters change.
3. Parcel loading: municipality mode → LPIS cache; otherwise fetch LPIS via bbox; if <3 parcels found → synthetic fallback.
4. Demo mode: `build_demo_data()` generates synthetic NDVI/NDRE/slope.
5. Real mode: if not connected → fallback to location-seeded synthetic; if connected → `build_real_data()` (synthetic with real weather) or `build_real_data_from_satellite()` (full openEO pipeline).
6. Crop filter → subset parcels/risks.
7. Map capped at 2000 parcels (sorted by risk descending).
8. Render: risk map → summary cards → top-5 risks + crop distribution → WOFOST summary + yield charts → time series → expandable data table → data source footnotes.

### Sidebar (`components/sidebar.py`)

Controls: Municipality dropdown (290 + "Custom location"), lat/lon inputs, date range, crop filter, demo toggle, WOFOST toggle, N input field, sowing date override, OIDC Connect/Verify/Disconnect, LPIS download, Refresh button, risk legend.

Warm earth styling: gradient green-to-brown background, black text (`#1a1a1a`), no backdrop-filter/rounded corners.

OIDC flow: Connect → device-code URL shown → user authenticates → Verify → connection stored in session state.

### Risk Map (`components/map.py`)

- **Framework**: Folium (Leaflet).
- **Base tiles**: CartoDB Positron (light) with Esri Satellite toggle via `LayerControl`.
- **Parcels**: Folium.Polygon with color-coded fill (`risk_label()`), stroke `#3d3229`, 1.2 px weight, 0.6 opacity.
- **Popups**: Parcel ID, crop, risk score/label, NDVI, NDRE, vigor z-score, heterogeneity, confidence, WOFOST yield, N surplus, N risk level, resolved crop.
- **Municipality boundary**: White dash-array polygon, auto-switches color between green (`#5a7d3c` on Positron) and white (`#ffffff` on Satellite) via Leaflet `baselayerchange` JS event listener.
- **Height**: 700px.
- **Max parcels**: 2000 (sorted by risk, remainder shown in computations only).

### Time Series (`components/timeseries.py`)

Three-row Plotly subplot (fourth row when WOFOST active):
1. NDVI per parcel (selected: highest-risk + lowest-risk + random sample).
2. SRRE per parcel (same selection).
3. Risk score histogram.
4. N surplus histogram (when WOFOST active).
- Colors: warm earth palette (sage greens `#5a7d3c`, warm browns `#a67c52`).
- Theme: `paper_bgcolor="#f2efe9"`, `plot_bgcolor="#ffffff"`, font `#4a3f35`, grid `#d4c9b8`.

WOFOST summary: 4-column metrics row (avg yield, total N surplus, high N-risk count, fallback mappings) + scatter plot of predicted yield per parcel.

### Data Table

Expandable `st.dataframe` with columns: Parcel, Crop, Area (ha), NDVI, NDRE, SRRE, Heterog., Runoff, Conf., Risk Score, Risk Level + optional WOFOST columns (Yield kg/ha, Total Yield kg, Total Yield t, N Surplus kg/ha, N Risk Level). Downloadable as CSV.

---

## Styling & Theme

**File**: `.streamlit/config.toml` + inline CSS in `main.py:16-71`.

**Warm earth palette**:
- Page background: `#f2efe9` (cream) with subtle radial gradient accents.
- Header gradient: `linear-gradient(90deg, #5a7d3c, #8b7355)` (sage → warm brown).
- Sidebar gradient: `linear-gradient(180deg, #5a7d3c, #8b7355)`, black text (`#1a1a1a`).
- Accent green: `#5a7d3c`, lighter green `#7a9d54`, `#8cb369`.
- Accent brown: `#8b7355`, `#7a6b5d`, `#d4a373`.
- Text: headings `#3d3229`, body `#4a3f35`, muted `#7a6b5d`.
- Cards/tables: white `#ffffff` backgrounds.
- Buttons: white bg, green border on hover.
- Plotly: matching paper/plot bg, sage markers, brown grid.

---

## Data Flow Summary

```
User input (municipality, dates, toggles)
  │
  ▼
LPIS fetch ──→ Parcel geometries + crop labels (12 types)
  │
  ▼
Satellite data (openEO) ──→ NDVI, NDRE, slope per parcel
  │                               │
  ▼                               ▼
compute_peer_baselines()      compute_zonal_stats()
(same-crop median + MAD)      (raster mask → mean)
  │                               │
  └───────────┬───────────────────┘
              ▼
      compute_risk_scores()
  (vigor_z + heterogeneity + ndre_diff + runoff) / 4
              │
              ▼
  ┌──── optional WOFOST pipeline ────┐
  │ Weather (Open-Meteo)              │
  │ Soil (SoilGrids)                  │
  │ CropResolver (LPIS → PCSE crop)   │
  │ run_single_wofost() per parcel    │
  │   (8× parallel ThreadPool)        │
  │ assess_overfertilization_risk()   │
  └───────────────────────────────────┘
              │
              ▼
      Streamlit Dashboard
  (map + summary cards + charts + table)
```

---

## Dependencies

Key packages (from `pyproject.toml`):
- `streamlit>=1.40.0` — dashboard framework
- `openeo>=0.50.0` — Copernicus Data Space API
- `pcse>=5.6.2` — WOFOST crop model
- `folium>=0.19.0` — interactive map
- `geopandas>=1.0.0`, `shapely>=2.0.0` — GIS operations
- `rasterio>=1.4.0`, `rioxarray>=0.20.0`, `xarray>=2025.0.0` — raster I/O
- `plotly>=6.0.0` — interactive charts
- `numpy>=2.4.6`, `pandas>=2.3.3` — data manipulation
- `owslib>=0.36.0` — WFS client for LPIS
- `requests>=2.31.0` — HTTP client

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Equal-weighted 4-component risk | Simplicity; synergy boost and sub-weights removed as over-parameterized |
| Vigor z-score scaled as `min(z/4 × 100, 100)` | z = 0 → 0, z = 4 (4σ outlier) → 100 |
| SRRE derived locally from NDRE | Eliminates need for 3rd openEO band; saves job time and cost |
| Thread-local YAML provider per parcel | PCSE Engine requires `set_active_crop()` which modifies shared state |
| Heuristic fallback in `_heuristic_result` | Graceful degradation when PCSE/WOFOST unavailable or fails |
| WOFOST yield = 0 at 62°N (known) | Default TSUM1/TSUM2 calibrated for Dutch climate; Swedish params needed |
| LPIS crop labels with disclaimer | Static snapshot; may not match actual sowing; user is warned |
| CartoDB Positron + Esri Satellite | Light map default complements warm theme; satellite available for context |
| Parcel border color `#3d3229` | Warm dark brown, consistent with earth-tone palette |
| Map height 700px | Balances visible area vs. scroll on 1080p screens |
| 2000 parcel cap on map | Folium performance; all parcels included in computations |

---

## Running the App

```bash
cd /home/uplong/Documents/digital_earth_hackathon
uv run streamlit run main.py
```

**Demo mode**: Works immediately with synthetic data. Toggle "Use demo data" on.

**Live satellite mode**:
1. Turn off demo toggle.
2. Click **Connect** → follow OIDC device-code URL → authenticate → click **Verify**.
3. Click **Fetch real satellite data** (~3 min for a single S2 batch job).

**WOFOST**: Enable "Enable WOFOST crop modeling" (requires real/connected mode). Currently yields 0 for Swedish climate with default parameters.

**National LPIS download** (one-time):
```bash
uv run python -m backend.lpis download
```
Downloads ~340 MB GeoParquet to `/tmp/godslingkollen_lpis/sweden.parquet`.

---

## Satellite Raster → Parcel Vector (Zonal Statistics)

Satellite imagery (Sentinel-2) is a **raster** — a grid of pixels with no knowledge of field boundaries. LPIS provides **vector polygons** — the parcel shapes. Bridging the two is the core of `compute_zonal_stats()` in `backend/satellite.py`.

**Step by step**:

1. **Coordinate transform**: Parcel geometry (EPSG:4326, lat/lon) is reprojected to UTM zone 33N (EPSG:32633) via `pyproj.Transformer` to match the raster's CRS.

2. **Raster masking** (`rasterio.mask.mask`): For each parcel polygon, the S2 GeoTIFF is masked — all pixels whose centres fall inside the polygon are extracted. The `all_touched=True` flag includes any pixel the polygon boundary touches (preserves partial-edge fields).

3. **Band extraction**: Two bands from the S2 composite:
   - Band 1 (NDVI) — crop greenness
   - Band 2 (NDRE) — red-edge chlorophyll
   
   For each band, NaN values (from cloud masking or no-data) are removed and the **mean** of valid pixels is computed. This yields `ndvi` and `ndre` per parcel.

4. **Spatial variance**: The standard deviation of NDVI within the parcel mask (`ndvi_std`) is computed as the heterogeneity metric.

5. **Data fraction**: `valid_pixels / total_pixels_in_mask` = `ndvi_data_frac` — this becomes the **confidence** score. A parcel with 80% cloud cover has low confidence (0.20).

6. **SRRE derivation**: After zonal stats, `srre = (1 + ndre_mean) / (1 - ndre_mean)` is computed from the per-parcel NDRE mean (not per-pixel).

7. **DEM slope**: The same masking process is applied to the slope raster (derived from Copernicus DEM via `np.gradient`). The mean slope per parcel drives the runoff risk component.

**Diagram**:

```
                  ┌─────────────────────────────┐
                  │  Sentinel-2 GeoTIFF          │
                  │  (two bands: NDVI, NDRE)     │
                  │  Cloud-masked, 20 m pixels   │
                  └──────────┬──────────────────┘
                             │
                  ┌──────────▼──────────────────┐
                  │  LPIS Parcel Polygon         │
                  │  (EPSG:4326 → EPSG:32633)    │
                  └──────────┬──────────────────┘
                             │
                  ┌──────────▼──────────────────┐
                  │  rasterio.mask.mask()        │
                  │  ⇒ pixel values inside       │
                  │     polygon boundary         │
                  └──────────┬──────────────────┘
                             │
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
     ndvi_mean         ndvi_std         ndvi_data_frac
     ndre_mean          (heterog.)        (confidence)
         │
         ▼
     srre = (1+NDRE)/(1-NDRE)
```

The result is a **flat list of dictionaries** — one per parcel — with keys `parcel_id`, `ndvi`, `ndre`, `ndvi_std`, `ndvi_data_frac`, `srre`, `slope`. This list feeds directly into `compute_risk_scores()`.

Without this step, the satellite data is just a raster image. Zonal statistics is what turns pixels into per-field risk scores.

## WOFOST + SoilGrids Integration

SoilGrids provides **static soil properties** (clay/sand/silt fractions) which are converted to WOFOST's **soil water parameters** (SMW, SMFCF, S0) via clay-based empirical thresholds. WOFOST then uses these parameters daily in its water balance to compute water stress, which directly affects LAI expansion, photosynthesis, and final yield. The yield drives the N-uptake estimate in the nutrient assessment.

The chain is:

```
SoilGrids (clay %) ──→ SMW, SMFCF, S0, AWC ──→ WOFOST water balance
                                                      │
                                                      ▼
                                              Daily soil moisture
                                              Water stress factor
                                              ↓ LAI / photosynthesis
                                                      │
                                                      ▼
                                              Simulated yield (TWSO)
                                                      │
                                                      ▼
                                              N uptake = yield × N_UPTAKE_PER_TONNE
```

Without SoilGrids, WOFOST uses hard-coded conservative defaults (25% clay → AWC 0.15). With SoilGrids, each query location gets clay/sand-specific hydrology — e.g., a sandy soil near Malmö gets lower SMFCF (0.18) and wilts faster than a clay soil in Skåne (SMFCF 0.40), producing different yield and N-surplus results.

---

## Future Work (from `future_work.md`)

1. **Crop type detection** from Sentinel-2 NDVI time series (remove LPIS label dependency).
2. **Real-time satellite ingest** via STAC + COGs (sub-minute response).
3. **Multi-year comparison** for risk trajectories.
4. **Ground-truth calibration** against Jordbruksverket trial data.
5. **Swedish WOFOST parameters** (recalibrate TSUM1/TSUM2 for 55–69°N).
6. **Parcel-level soil data** from Markinfo/SGAP (SoilGrids 250m is too coarse).
