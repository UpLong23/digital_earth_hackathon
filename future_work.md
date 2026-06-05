# Future Work

Ideas and improvements beyond the hackathon scope.

## Crop Type Detection

LPIS data has no time dimension — it is a static snapshot of the latest
annual declaration from Jordbruksverket. If a farm rotates crops between
years, WOFOST simulates the wrong crop, making yield and N-uptake
predictions unreliable.

**Desired solution**: Classify actual crop type from Sentinel-2 NDVI
time series using phenological curve matching or a lightweight ML
classifier (e.g., Random Forest on temporal features). This would:

- Remove dependency on LPIS crop labels entirely
- Work for any year/season without waiting for declarations
- Enable detection of cover crops, catch crops, and undersown crops
  not captured by LPIS
- Provide per-parcel crop confidence scores

## Real-Time Satellite Ingest

The current openEO pipeline is batch-oriented (~5 min run). For an
interactive tool, a tile-based streaming approach (e.g., STAC + COGs)
would give sub-minute response for small regions.

## Multi-Year Comparison

Show risk trajectories per parcel across years to highlight management
changes or degradation trends. Requires storing zonal stats per season.

## Ground-Truth Calibration

Maps risk scores to field-observed overfertilization (e.g.,
Jordbruksverket's "Växtnäringsförsök" trial data) to calibrate
thresholds and validate the four-component risk formula.

## Swedish WOFOST Parameters

Default TSUM1/TSUM2 parameters are calibrated for Dutch/continental
climate. For Swedish agriculture (55–69°N), temperature sums need
recalibration from Phenology Sweden or SCB trial data.

## Soil Data at Parcel Level

SoilGrids at 250 m resolution is too coarse for individual fields. Use
the Swedish "Markinfo" dataset or SLU's "SGAP" for parcel-level soil
properties.
