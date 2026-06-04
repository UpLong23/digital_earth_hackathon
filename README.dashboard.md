# 🌾 Gödslingskollen — Overfertilization Monitor for Sweden

> Hackathon project: Real-time overfertilization risk monitoring for Swedish farmers and municipalities using Copernicus satellite data.

## The Problem

Swedish agriculture faces strict regulations on nitrogen and phosphorus application. Overfertilization leads to:

- **Eutrophication** of the Baltic Sea (Sweden's #1 water quality issue)
- **Nitrate leaching** into groundwater
- **Financial loss** for farmers buying unnecessary fertilizer
- **Non-compliance** with cross-compliance requirements for EU CAP subsidies

Currently, monitoring is done via random field inspections — sparse, expensive, and reactive.

## The Solution

**Gödslingskollen** combines Sentinel-1 (radar), Sentinel-2 (optical), Digital Terrain Model, LPIS parcel data, and the National Landcover Database (NMD) to produce **field-level overfertilization risk scores** updated every satellite overpass.

### Key Features

| Feature | Data Source | What It Detects |
|---|---|---|
| **Crop Nitrogen Status** | Sentinel-2 (NDVI, REIP, CIgreen) | Chlorophyll content → proxy for N uptake |
| **Manure Spreading Events** | Sentinel-1 (SAR backscatter change) | sudden soil moisture/texture change from spreading |
| **Runoff Risk** | DTM (slope, flow accumulation) | Fields where excess N will wash into waterways |
| **Crop Type Verification** | LPIS + Sentinel-2 time series | Is the reported crop actually growing? |
| **Buffer Zone Compliance** | NMD + LPIS | Fertilizer application near water bodies |
| **Historical Trend** | All of the above | Is N status increasing year-over-year? |

### How It Works (Flow)

```
Sentinel-2 ──→ Vegetation Indices ──→ N Status per parcel
Sentinel-1 ──→ Change Detection ──→ Spreading events flagged
DTM        ──→ Slope / Flow Accum ──→ Runoff risk layer
LPIS       ──→ Parcel boundaries & crop registry ──→ Field identification
NMD        ──→ Land cover mask ──→ Only agricultural land scored
                        ↓
           openEO backend (cloud processing)
                        ↓
        ┌───────────────┴───────────────┐
        ↓                               ↓
  Streamlit Dashboard            GeoJSON export
  (interactive maps,             (for GIS tools)
   time series, alerts)
```

---

## Tech Stack

| Component | Tool | Why |
|---|---|---|
| **Language** | Python 3.14 | Modern, fast, great geospatial ecosystem |
| **Satellite access** | [openEO](https://openeo.org) (already in deps) | Unified API for Sentinel-1/2 + DTM on CDSE/EOCloud |
| **Dashboard** | [Streamlit](https://streamlit.io) | Fastest path to interactive map dashboard in 1 day |
| **Vector data** | GeoPandas, Shapely | LPIS parcel handling, spatial joins |
| **Raster processing** | Xarray + rioxarray | Satellite raster stacks, index computation |
| **Map visualization** | [pydeck](https://deckgl.readthedocs.io) or Folium | Large geospatial layers in browser |
| **Charts** | Plotly | Interactive time series of vegetation indices |
| **Package manager** | `uv` | Fast, reliable Python packaging |
| **Authentication** | openEO account | Free CDSE (Copernicus Data Space Ecosystem) account |

### Dependencies to add to `pyproject.toml`

```
streamlit
geopandas
shapely
xarray
rioxarray
rasterio
plotly
pydeck
folium
```

---

## Quick Start

```bash
# Install uv if needed: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run streamlit run main.py
```

1. Set up a free [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu) account
2. Configure openEO credentials (`openeo connect` or environment variables)
3. Default region: Svalöv municipality (Skåne) — Sweden's most productive agricultural area
4. Watch the overfertilization risk map render

---

## Data Sources

| Dataset | Access | Use |
|---|---|---|
| **Sentinel-2 L2A** | openEO `SENTINEL2_L2A` | 10m multispectral, vegetation indices |
| **Sentinel-1 GRD** | openEO `SENTINEL1_GRD` | 10m radar, change detection for spreading |
| **EU-DTM (Copernicus)** | openEO `EU_DTM` | 25m digital terrain, slope/runoff |
| **LPIS** | Swedish Board of Agriculture (`jordbruksverket.se`) | Field boundaries + declared crops |
| **NMD** | Swedish Environmental Protection Agency (`naturvardsverket.se`) | Land cover classification |

### Key Vegetation Indices for Nitrogen Detection

| Index | Formula (Sentinel-2 Bands) | What It Tells You |
|---|---|---|
| **NDVI** | `(B08 - B04) / (B08 + B04)` | General vegetation greenness — low = stressed/overfertilized |
| **REIP** | Red Edge Inflection Point (B05, B06, B07) | Chlorophyll content — directly correlated with N uptake |
| **NDRE** | `(B08 - B06) / (B08 + B06)` | Canopy N status — less saturated than NDVI in high biomass |
| **CIgreen** | `(B08 / B03) - 1` | Chlorophyll index — sensitive to N deficiency |

**Pro tip**: REIP and NDRE are better predictors of crop nitrogen status than NDVI because they use the red-edge bands (B05, B06, B07) which are sensitive to chlorophyll without saturating at high biomass.

---

## Hackathon Day Plan

| Hour | Task |
|---|---|
| 0–1 | Set up openEO connection, fetch S2 image for test area |
| 1–2 | Compute NDVI/REIP/NDRE time series over LPIS parcels using xarray |
| 2–3 | Add DTM slope analysis, build runoff risk layer |
| 3–4 | Wire everything into Streamlit: base map + parcel overlay |
| 4–5 | Add time series charts, color parcels by N risk |
| 5–6 | Add S-1 change detection for manure spreading flags |
| 6–7 | Polish UI, add filters (crop type, date range, municipality) |
| 7–8 | **Present!** |

---

## Architecture

```
main.py                  ← Streamlit entry point
├── backend/
│   ├── sentinel.py      ← openEO queries for S1, S2, DTM
│   ├── indices.py       ← Vegetation index computation (NDVI, REIP, NDRE)
│   ├── parcels.py       ← LPIS parsing + spatial join
│   ├── risk.py          ← Overfertilization risk model
│   └── data.py          ← Caching, local storage (NetCDF via h5netcdf)
├── assets/
│   └── sample_lpis.geojson
├── components/
│   ├── map.py           ← pydeck map rendering
│   ├── timeseries.py    ← Plotly chart component
│   └── sidebar.py       ← Filter controls
└── config.py            ← openEO credentials, constants
```

---

## Code Patterns (from the Crisis Management Hackathon)

### Loading Sentinel-2 data with xarray

```python
import xarray as xr

# NetCDF data from openEO
s2_10m = xr.open_dataset("s2_10m.nc", engine="h5netcdf")
time_dim = "t" if "t" in s2_10m.dims else "time"

# Extract bands for a given time step
red   = s2_10m["B04"].sel({time_dim: time_step}).values
nir   = s2_10m["B08"].sel({time_dim: time_step}).values
green = s2_10m["B03"].sel({time_dim: time_step}).values

# NDVI
ndvi = (nir - red) / (nir + red + 1e-10)

# True color composite (RGB)
rgb = np.dstack((red, green, blue))
rgb = np.clip(rgb / 3000.0, 0, 1)
```

### Computing NDVI time series over parcels

```python
# For each LPIS parcel, extract zonal statistics of NDVI over time
# openEO returns xarray DataArrays with spatial (x, y) + temporal (t) dims
ndvi_mean = ndvi_stack.mean(dim=["x", "y"])  # mean per time step

# Change detection — flag sudden drops
diff = ndvi_mean.diff(dim=time_dim)
alerts = diff < -0.15  # threshold for possible overfertilization
```

---

## Risk Scoring Model

```
Risk = w1 * (1 - N_uptake_norm) + w2 * runoff_potential + w3 * spreading_flag + w4 * crop_factor

where:
  N_uptake_norm    = normalized REIP/NDRE (low = overfertilized, high N available but unused)
  runoff_potential = slope from DTM + proximity to water bodies from NMD
  spreading_flag   = 1 if S-1 SAR detected sudden backscatter change in last 14 days
  crop_factor      = N-demand of declared crop (from LPIS): e.g., wheat=0.8, rapeseed=0.6, ley=0.4
  w1, w2, w3, w4   = tunable weights (default: 0.4, 0.25, 0.2, 0.15)
```

### Interpreting the Score

| Score | Label | Action |
|---|---|---|
| 0–30 | 🟢 Low Risk | Normal |
| 30–60 | 🟡 Moderate | Advise reduced spreading next pass |
| 60–80 | 🟠 High | Flag for inspection |
| 80–100 | 🔴 Critical | Immediate notification to municipality |

---

## Why This Wins

- **Practical**: Swedish municipalities need this for EU CAP compliance monitoring
- **Actionable**: Farmers can adjust spreading based on actual crop uptake, not calendar
- **Feasible**: openEO handles all satellite access in ~50 lines of Python
- **Scalable**: Works for one field or all of Sweden
- **Demo-ready**: Streamlit produces a stunning live dashboard in hours
- **Proven data patterns**: Same xarray/NetCDF pipeline used in the Digital Earth Sweden Crisis Management Hackathon (Stenungsund landslide, Kårböle wildfire) — now adapted for agricultural monitoring
