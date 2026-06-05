# Gödslingskollen — Overfertilization Risk Monitor

Detects possible overfertilization on Swedish farmland using Sentinel-2 NDVI/NDRE, within-field heterogeneity, terrain runoff potential, and **WOFOST crop growth simulation**.

```
godslingkollen/
├── main.py                            Entry point — Streamlit app layout, session state, data dispatch
├── config.py                          Constants: openEO endpoint, crop N-demand, WOFOST settings
│
├── backend/
│   ├── risk.py                        Heuristic risk engine + compute_combined_risk() interface
│   ├── satellite.py                   openEO batch job (S2 NDVI/NDRE), DEM download, zonal stats
│   ├── real.py                        Data orchestrator: satellite + WOFOST pipeline integration
│   ├── data.py                        Synthetic demo data generator
│   ├── parcels.py                     Parcel loading/ generation/ filtering
│   ├── lpis.py                        LPIS handler: fiboa Sweden GeoParquet, WFS, SAM crop codes
│   ├── municipalities.py              290 Swedish municipality boundaries
│   ├── wofost.py                      CropResolver + WOFOST model runner + feature enrichment
│   ├── weather.py                     Open-Meteo weather fetcher → PCSE-compatible DataFrame
│   ├── soil.py                        SoilGrids soil properties → WOFOST parameters
│   ├── nutrient.py                    N-uptake/surplus/efficiency + overfertilization assessment
│   ├── cache.py                       JSON file cache with TTL
│   └── historical.py                  Empty (legacy)
│
├── components/
│   ├── sidebar.py                     Streamlit sidebar: municipality, dates, WOFOST/nutrient toggles
│   ├── map.py                         Folium risk map + WOFOST popup fields
│   └── timeseries.py                  Plotly charts: NDVI, SRRE, risk histogram, N surplus, WOFOST summary
│
├── assets/
│   ├── swedish_municipalities.geojson  290 municipality boundaries
│   └── sample_parcels.geojson          10 fallback parcels (Svalöv)
│
├── .streamlit/config.toml
├── pyproject.toml
└── README.md
```

## Run

```bash
uv run streamlit run main.py
```

## Pipeline

1. **Parcel loading** — LPIS (fiboa Sweden GeoParquet or WFS), municipality filter, synthetic fallback
2. **Satellite features** — Sentinel-2 NDVI/NDRE at 20m + DEM slope via openEO
3. **Heuristic risk** — Equal-weighted score: vigor z-score, heterogeneity, red-edge anomaly, runoff
4. **WOFOST simulation** (optional) — Per-parcel crop growth with dynamic PCSE model selection
5. **Nutrient assessment** — N surplus, use efficiency, leaching/runoff flags, overfertilization score
6. **Visualization** — Full-width risk map, summary cards, time series, N surplus histogram, data table

## New WOFOST modules

| Module | Purpose |
|--------|---------|
| `backend/wofost.py` | Crop resolution (dynamic PCSE YAML provider), WOFOST model runner, LAI/chlorophyll proxies |
| `backend/weather.py` | Open-Meteo historical/forecast weather → PCSE `WOFOST80SiteDataProvider`-compatible |
| `backend/soil.py` | SoilGrids REST API → WOFOST soil water parameters (clay-based SMW/SMFCF/S0) |
| `backend/nutrient.py` | N budget (uptake, removal, surplus, efficiency), multi-factor risk score, recommendations |
| `backend/cache.py` | JSON file cache with TTL for weather/soil queries |

## Data sources

| Dataset | Source | Module |
|---------|--------|--------|
| Sentinel-2 L2A | Copernicus Data Space (openEO) | `satellite.py` |
| EU-DTM | Copernicus Data Space (openEO) | `satellite.py` |
| LPIS parcels | fiboa Sweden / Jordbruksverket WFS | `lpis.py` |
| Municipality boundaries | Static GeoJSON | `municipalities.py` |
| Crop codes | SAM inline mapping | `lpis.py` |
| **Weather** | **Open-Meteo** (archive/forecast) | `weather.py` |
| **Soil** | **SoilGrids** (ISRIC REST API) | `soil.py` |
| **Crop parameters** | **PCSE YAML crop provider** | `wofost.py` |

## Migration note

- Added `pcse>=5.6.2` to dependencies (required for WOFOST simulations)
- Added `requests>=2.31.0` for Open-Meteo and SoilGrids API calls (already transitively present via openeo)
- `backend/wofost.py` replaces the previous `backend/historical.py` intention
- All WOFOST runs are optional: heuristic-only mode remains the default
- Demo mode uses heuristic fallback when WOFOST is enabled without real data
