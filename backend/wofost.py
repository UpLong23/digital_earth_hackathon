import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CROP_PARAM_DIR = Path("/tmp/WOFOST_crop_parameters")

# ── Crop synonym mapping ─────────────────────────────────────────
CROP_SYNONYMS = {
    "sugarbeet": "sugar beet",
    "sugar_beet": "sugar beet",
    "rapeseed": "oilseed rape",
    "spring rapeseed": "spring oilseed rape",
    "winter rapeseed": "winter oilseed rape",
    "peas": "pea",
    "field beans": "field bean",
    "brown beans": "field bean",
    "maize": "maize",
    "corn": "maize",
    "winter wheat": "winter wheat",
    "spring wheat": "spring wheat",
    "winter barley": "winter barley",
    "spring barley": "spring barley",
    "oats": "oat",
    "rye": "rye",
    "potato": "potato",
    "sugar beet": "sugar beet",
    "ley": "grass",
    "grass": "grass",
    "pasture": "grass",
    "fallow": None,
}

SEASONAL_TERMS = {"winter", "spring", "summer", "autumn"}

# Built-in crop list for Swedish agriculture (used when PCSE YAML unavailable)
BUILTIN_CROPS = {
    "winter wheat": {"default", "winter_wheat"},
    "spring wheat": {"default", "spring_wheat"},
    "winter barley": {"default", "winter_barley"},
    "spring barley": {"default", "spring_barley"},
    "oat": {"default"},
    "rye": {"default"},
    "maize": {"default", "grain_maize", "silage_maize"},
    "potato": {"default"},
    "sugar beet": {"default"},
    "oilseed rape": {"default", "winter_rape", "spring_rape"},
    "spring oilseed rape": {"default", "spring_rape"},
    "winter oilseed rape": {"default", "winter_rape"},
    "pea": {"default"},
    "field bean": {"default"},
    "grass": {"default"},
    "alfalfa": {"default"},
    "set-aside": {"default"},
}


class CropResolver:
    """Resolves Swedish LPIS/SAM crop labels to WOFOST crop/variety names.

    Discovers available crops from PCSE's YAML crop provider at runtime.
    Falls back to a built-in Swedish crop list if PCSE data unavailable.
    """

    def __init__(self):
        self._crops = None
        self._varieties = None

    def _load_crops(self):
        if self._crops is not None:
            return
        # Try PCSE YAML provider from local repo first
        try:
            from pcse.input import YAMLCropDataProvider
            from pcse.models import Wofost72_WLP_FD

            provider = YAMLCropDataProvider(model=Wofost72_WLP_FD, fpath=str(CROP_PARAM_DIR),
                                            force_reload=False)
            self._crops = {}
            for crop_id, varieties in provider._store.items():
                crop = str(crop_id).lower()
                self._crops[crop] = set(v.lower() for v in varieties.keys())
            if not self._crops:
                raise ValueError("No crops discovered from PCSE")
        except Exception as exc:
            logger.warning(f"PCSE crop provider failed ({exc}), using built-in list")
            self._crops = BUILTIN_CROPS
        self._varieties = {v for vs in self._crops.values() for v in vs}

    def list_supported_crops(self) -> dict:
        """Return {crop_name: [varieties]} from PCSE."""
        self._load_crops()
        return {k: sorted(v) for k, v in sorted(self._crops.items())}

    def resolve_crop(self, label: str) -> dict:
        """Resolve a crop label to WOFOST crop + variety.

        Returns:
            dict with keys: crop, variety, match_type, warning
        """
        self._load_crops()
        label_l = label.strip().lower()

        # Special cases
        if label_l in {"fallow", "non-eligible land", "buffer zone", "wetland"}:
            return {
                "crop": None, "variety": None,
                "match_type": "no_simulation",
                "warning": "No crop simulation for fallow/set-aside",
            }

        # Check for exact match first
        if label_l in self._crops:
            var = self._pick_variety(label_l)
            return {
                "crop": label_l, "variety": var,
                "match_type": "exact", "warning": None,
            }

        # Synonym resolution
        normalized = CROP_SYNONYMS.get(label_l)
        if normalized is not None and normalized in self._crops:
            var = self._pick_variety(normalized)
            return {
                "crop": normalized, "variety": var,
                "match_type": "synonym", "warning": f"Mapped '{label}' -> '{normalized}'",
            }
        if normalized is None and label_l in CROP_SYNONYMS:
            return {
                "crop": None, "variety": None,
                "match_type": "no_simulation",
                "warning": f"'{label}' mapped to fallback/no-simulation crop",
            }

        # Seasonal qualifier match
        for crop_name in self._crops:
            crop_parts = set(crop_name.replace("-", " ").split())
            label_parts = set(label_l.replace("-", " ").split())
            seasonal = crop_parts & SEASONAL_TERMS
            if seasonal and (crop_parts - seasonal) == (label_parts - seasonal):
                var = self._pick_variety(crop_name)
                return {
                    "crop": crop_name, "variety": var,
                    "match_type": "seasonal",
                    "warning": f"Seasonal match: '{label}' -> '{crop_name}'",
                }

        # Substring match
        for crop_name in self._crops:
            if crop_name in label_l or label_l in crop_name:
                var = self._pick_variety(crop_name)
                return {
                    "crop": crop_name, "variety": var,
                    "match_type": "substring",
                    "warning": f"Substring match: '{label}' -> '{crop_name}'",
                }

        # Token overlap
        best_score = 0
        best_crop = None
        for crop_name in self._crops:
            crop_tokens = set(crop_name.replace("-", " ").split())
            label_tokens = set(label_l.replace("-", " ").split())
            overlap = len(crop_tokens & label_tokens)
            if overlap > best_score:
                best_score = overlap
                best_crop = crop_name
        if best_score >= 1:
            var = self._pick_variety(best_crop)
            return {
                "crop": best_crop, "variety": var,
                "match_type": "fuzzy_token",
                "warning": f"Fuzzy match: '{label}' -> '{best_crop}'",
            }

        return {
            "crop": None, "variety": None,
            "match_type": "fallback",
            "warning": f"Could not resolve '{label}' to any WOFOST crop",
        }

    def _pick_variety(self, crop_name):
        varieties = self._crops.get(crop_name, set())
        if not varieties:
            return "default"
        for preferred in ["spring", "default", "grain"]:
            for v in varieties:
                if preferred in v:
                    return v
        return sorted(varieties)[0]


# ── Feature enrichment helpers (from existing satellite features) ──

def lai_from_ndvi(ndvi: Optional[float]) -> Optional[float]:
    """LAI proxy from NDVI using empirical formula, clamped safely."""
    if ndvi is None or ndvi <= 0:
        return None
    lai = 0.57 * np.exp(3.45 * ndvi)
    return min(max(lai, 0.1), 8.0)


def chlorophyll_proxy(ndre: Optional[float], lai: Optional[float]) -> Optional[float]:
    """Canopy chlorophyll proxy from NDRE and LAI."""
    if ndre is None or lai is None:
        return None
    return ndre * min(lai, 4.0) / 4.0


def runoff_stress_factor(slope_pct: float) -> float:
    """Runoff stress factor between 0 (flat) and 1 (steep)."""
    if slope_pct <= 0.5:
        return 0.0
    if slope_pct > 10:
        return 1.0
    return slope_pct / 10.0


def observation_quality(confidence: float, heterogeneity: float) -> str:
    """Parcel observation quality label."""
    if confidence >= 0.8 and heterogeneity < 0.15:
        return "good"
    if confidence >= 0.5:
        return "moderate"
    return "poor"


def parcel_features_enrichment(risk_row: dict) -> dict:
    """Derive WOFOST calibration proxies from existing risk engine output."""
    ndvi = risk_row.get("ndvi")
    ndre = risk_row.get("ndre")
    lai = lai_from_ndvi(ndvi)
    return {
        "lai_proxy": lai,
        "chl_proxy": chlorophyll_proxy(ndre, lai),
        "runoff_stress": runoff_stress_factor(risk_row.get("runoff_score", 0) / 95.0 * 10),
        "obs_quality": observation_quality(
            risk_row.get("confidence", 0),
            risk_row.get("heterogeneity_score", 0) / 100.0,
        ),
    }


# ── WOFOST model runner ─────────────────────────────────────────

def _detect_model_class():
    """Detect best available WOFOST model class from PCSE, preferring nutrient+water-limited."""
    variants = [
        "Wofost80_NWLP_FD_beta",
        "Wofost80_WLP_FD_beta",
        "Wofost72_WLP_FD",
    ]
    import importlib
    for name in variants:
        try:
            mod = importlib.import_module(f"pcse.models")
            cls = getattr(mod, name, None)
            if cls is not None:
                return name, cls
        except Exception:
            continue
    return None, None


def _make_soil_params(soil_data: dict) -> dict:
    """Build WOFOST-compatible soil parameter dict."""
    return {
        "SMW": soil_data.get("smw", 0.12),
        "SMFCF": soil_data.get("smfc", 0.30),
        "S0": soil_data.get("s0", 0.40),
        "CRAIRC": 0.05,
        "SOPE": 10.0,
        "KSUB": 1.0,
        "WAV": soil_data.get("available_water_capacity", 0.15) * 100.0,
        "K0": 0.01,
    }



def _build_weather_provider(weather_df: pd.DataFrame, lat: float, lon: float):
    """Build a shared WeatherDataProvider from a DataFrame (reused across parcels)."""
    from pcse.base import WeatherDataProvider
    from pcse.base.weather import WeatherDataContainer
    from pcse.util import reference_ET

    containers = {}
    for _, row in weather_df.iterrows():
        day = row["DAY"].to_pydatetime() if hasattr(row["DAY"], "to_pydatetime") else row["DAY"]
        tmin = float(row["TMIN"]); tmax = float(row["TMAX"])
        irrad = float(row["IRRAD"]); vap = float(row["VAP"])
        wind = float(row["WIND"]); rain = float(row["RAIN"])
        et0_ref = float(row.get("ET0", 0))
        try:
            e0_r, es0_r, et0_r = reference_ET(day, lat, 50.0, tmin, tmax, irrad, vap, wind,
                                              ANGSTA=0.25, ANGSTB=0.50)
            e0 = max(0.0, min(e0_r, 2.5)); es0 = max(0.0, min(es0_r, 2.5)); et0 = max(0.0, min(et0_r, 2.5))
        except Exception:
            e0, es0, et0 = max(et0_ref * 1.1, 0.0), max(et0_ref * 0.9, 0.0), max(et0_ref, 0.5)
        wdc = WeatherDataContainer(
            LAT=lat, LON=lon, ELEV=50.0, DAY=day,
            IRRAD=irrad, TMIN=tmin, TMAX=tmax, VAP=vap, RAIN=rain,
            E0=e0, ES0=es0, ET0=et0, WIND=wind,
            TEMP=float(row.get("TEMP", (tmin + tmax) / 2)),
        )
        containers[(day, 0)] = wdc
    provider = WeatherDataProvider()
    provider.store = containers
    provider.latitude = lat; provider.longitude = lon; provider.elevation = 50.0
    provider.description = "Open-Meteo"
    return provider


def _prepare_wofost_bundle(lat, lon, weather_df, soil_data) -> Optional[dict]:
    """Create shared resources for batch WOFOST runs.

    Returns a dict with model_cls, crop_store, weather_provider, soil_params, etc.
    Returns None if PCSE models or crop parameters are unavailable.
    """
    from pcse.input import YAMLCropDataProvider

    model_name, model_cls = _detect_model_class()
    if model_cls is None:
        return None

    crop_provider = YAMLCropDataProvider(model=model_cls, fpath=str(CROP_PARAM_DIR),
                                         force_reload=False)
    if not crop_provider._store:
        return None

    if model_name.startswith("Wofost72"):
        from pcse.fileinput import WOFOST72SiteDataProvider as SDP
    elif model_name.startswith("Wofost73"):
        from pcse.fileinput import WOFOST73SiteDataProvider as SDP
    else:
        from pcse.fileinput import WOFOST81SiteDataProvider_Classic as SDP

    return {
        "model_cls": model_cls,
        "model_name": model_name,
        "crop_store": crop_provider._store,
        "weather_provider": _build_weather_provider(weather_df, lat, lon),
        "sdp_cls": SDP,
        "wav": soil_data.get("available_water_capacity", 0.15) * 100.0,
        "soil_params": {
            "SMFCF": soil_data.get("smfc", 0.30),
            "SM0": soil_data.get("s0", 0.40),
            "SMW": soil_data.get("smw", 0.12),
            "CRAIRC": 0.05, "K0": 0.01, "SOPE": 10.0, "KSUB": 1.0, "RDMSOL": 0.2,
        },
        "weather_df": weather_df,
        "soil_data": soil_data,
    }


def run_single_wofost(
    crop_label: str,
    lat: float,
    lon: float,
    season_start,
    season_end,
    bundle: dict,
    parcel_features: Optional[dict] = None,
    sowing_date: Optional[date] = None,
) -> dict:
    """Run WOFOST for one parcel using a pre-built resource bundle.

    bundle comes from _prepare_wofost_bundle(). Returns the same result
    structure as run_wofost_simulation.
    """
    from pcse.base import ParameterProvider
    from pcse.input import YAMLCropDataProvider

    if isinstance(season_start, str):
        season_start = date.fromisoformat(season_start)
    if isinstance(season_end, str):
        season_end = date.fromisoformat(season_end)

    resolver = CropResolver()
    resolved = resolver.resolve_crop(crop_label)
    crop_name = resolved.get("crop")

    if crop_name is None:
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            bundle["soil_data"], parcel_features,
        )

    if sowing_date is None:
        sowing_date = date(season_start.year, 4, 20)

    # Thread-local YAML provider (cheap after first load due to cache)
    crop_provider = YAMLCropDataProvider(model=bundle["model_cls"],
                                         fpath=str(CROP_PARAM_DIR),
                                         force_reload=False)
    if not crop_provider._store:
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            bundle["soil_data"], parcel_features,
            warning_extras=["No crop parameter files"],
        )

    # Find YAML crop + variety
    yaml_crop_name = None
    for cn in crop_provider._store:
        if cn.lower() in crop_name.lower() or crop_name.lower() in cn.lower():
            yaml_crop_name = cn
            break
    if yaml_crop_name is None:
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            bundle["soil_data"], parcel_features,
            warning_extras=[f"No YAML crop file for '{crop_name}'"],
        )

    all_varieties = list(crop_provider._store[yaml_crop_name].keys())
    yaml_variety = None
    season_hint = ""
    if "winter" in crop_name.lower():
        season_hint = "winter"
    elif "spring" in crop_name.lower():
        season_hint = "spring"
    for v in all_varieties:
        if season_hint and season_hint in v.lower():
            yaml_variety = v; break
    if yaml_variety is None:
        for v in all_varieties:
            if "default" in v.lower() or "1" in v:
                yaml_variety = v; break
    if yaml_variety is None:
        yaml_variety = all_varieties[0]
    crop_provider.set_active_crop(yaml_crop_name, yaml_variety)

    # Site data
    sdp_cls = bundle["sdp_cls"]
    site = sdp_cls(WAV=bundle["wav"])

    # Parameter provider
    params = ParameterProvider(
        sitedata=site,
        soildata=bundle["soil_params"],
        cropdata=crop_provider,
    )

    # Agro management
    agro_data = [{
        season_start: {
            "CropCalendar": {
                "crop_name": yaml_crop_name,
                "variety_name": yaml_variety,
                "crop_start_date": sowing_date,
                "crop_start_type": "sowing",
                "crop_end_date": None,
                "crop_end_type": "maturity",
                "max_duration": max(1, (season_end - season_start).days),
            },
            "TimedEvents": None,
            "StateEvents": None,
        },
    }]

    try:
        wofost = bundle["model_cls"](params, bundle["weather_provider"], agro_data)
        sim_end = min(season_end, bundle["weather_provider"].last_date)
        wofost.run_till(sim_end.isoformat())
        output = wofost.get_output()
        if not output:
            raise ValueError("Empty output")

        final = output[-1]
        daily_df = _output_to_dataframe(output)
        yield_kg_ha = final.get("TWSO", 0) * 1000.0
        if yield_kg_ha <= 0:
            logger.warning(f"WOFOST simulated 0 yield for {crop_label} at lat={lat:.1f}")

        return {
            "resolved_crop": crop_name,
            "resolved_variety": yaml_variety,
            "match_type": resolved["match_type"],
            "model": bundle["model_name"],
            "nutrient_aware": "NWLP" in bundle["model_name"],
            "yield_kg_ha": yield_kg_ha,
            "total_yield_kg": None,
            "total_yield_tonnes": None,
            "biomass_kg_ha": final.get("TAGP", 0) * 1000.0,
            "peak_lai": max((o.get("LAI") or 0) for o in output),
            "water_use_indicators": {
                "transpiration_mm": sum((o.get("TRA") or 0) for o in output),
                "precipitation_mm": bundle["weather_df"]["RAIN"].sum(),
                "water_deficit_mm": 0,
            },
            "daily": daily_df,
            "fallback_flags": [],
            "confidence": "high",
            "warning": resolved["warning"],
        }
    except Exception as exc:
        logger.warning(f"WOFOST failed for {crop_label}: {exc}")
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            bundle["soil_data"], parcel_features,
            warning_extras=[str(exc)],
        )


def run_wofost_simulation(
    crop_label: str,
    lat: float,
    lon: float,
    season_start,
    season_end,
    soil_data: dict,
    weather_df: pd.DataFrame,
    parcel_features: Optional[dict] = None,
    sowing_date: Optional[date] = None,
) -> dict:
    """Run WOFOST crop simulation for a parcel.

    Returns a result dict with yield, biomass, water/nutrient indicators,
    or a heuristic fallback on failure.
    """
    # Normalise str → date
    if isinstance(season_start, str):
        season_start = date.fromisoformat(season_start)
    if isinstance(season_end, str):
        season_end = date.fromisoformat(season_end)

    resolver = CropResolver()
    resolved = resolver.resolve_crop(crop_label)
    crop_name = resolved.get("crop")
    variety = resolved.get("variety")

    if crop_name is None:
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            soil_data, parcel_features,
        )

    if sowing_date is None:
        sowing_date = date(season_start.year, 4, 20)

    model_name, model_cls = _detect_model_class()
    if model_cls is None:
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            soil_data, parcel_features,
            warning_extras=["PCSE models not available, using heuristic yield"],
        )

    try:
        from datetime import timedelta

        # Check if PCSE crop parameter files are available
        from pcse.input import YAMLCropDataProvider
        crop_provider = YAMLCropDataProvider(model=model_cls, fpath=str(CROP_PARAM_DIR),
                                             force_reload=False)
        if not crop_provider._store:
            raise ValueError("No crop parameter files found - install pcse_crop_parameters")

        # Find the YAML crop name that matches the resolved crop
        yaml_crop_names = list(crop_provider._store.keys())
        yaml_crop_name = None
        for cn in yaml_crop_names:
            if cn.lower() in crop_name.lower() or crop_name.lower() in cn.lower():
                yaml_crop_name = cn
                break
        if yaml_crop_name is None:
            msg = f"No YAML crop file matches '{crop_name}' (available: {yaml_crop_names[:5]}...)"
            raise ValueError(msg)
        logger.info(f"YAML crop: {yaml_crop_name}, all_varieties: {list(crop_provider._store[yaml_crop_name].keys())}")

        # Find a matching variety
        all_varieties = list(crop_provider._store[yaml_crop_name].keys())
        yaml_variety = None
        if variety and variety in all_varieties:
            yaml_variety = variety
        elif all_varieties:
            # Priority: match seasonal term (winter/spring) in variety name
            season_hint = ""
            if "winter" in crop_name.lower():
                season_hint = "winter"
            elif "spring" in crop_name.lower():
                season_hint = "spring"
            for v in all_varieties:
                if season_hint and season_hint in v.lower():
                    yaml_variety = v
                    break
            if yaml_variety is None:
                for v in all_varieties:
                    if "default" in v.lower() or "1" in v:
                        yaml_variety = v
                        break
            if yaml_variety is None:
                yaml_variety = all_varieties[0]
        if yaml_variety:
            crop_provider.set_active_crop(yaml_crop_name, yaml_variety)
            logger.info(f"Active crop: {crop_provider.current_crop_name}/{crop_provider.current_variety_name}")
        else:
            raise ValueError(f"No variety found for crop '{yaml_crop_name}' (available: {all_varieties})")

        # Site data by model version
        if model_name.startswith("Wofost72"):
            from pcse.fileinput import WOFOST72SiteDataProvider as SiteDataProvider
        elif model_name.startswith("Wofost73"):
            from pcse.fileinput import WOFOST73SiteDataProvider as SiteDataProvider
        else:
            from pcse.fileinput import WOFOST81SiteDataProvider_Classic as SiteDataProvider

        wav = soil_data.get("available_water_capacity", 0.15) * 100.0
        site = SiteDataProvider(WAV=wav)
        # Convert DataFrame to WeatherDataContainer list
        from pcse.base import WeatherDataProvider
        from pcse.base.weather import WeatherDataContainer
        from pcse.util import reference_ET

        # Build containers bypassing range validation by using object.__setattr__
        weather_containers = {}
        for _, row in weather_df.iterrows():
            day = row["DAY"].to_pydatetime() if hasattr(row["DAY"], "to_pydatetime") else row["DAY"]
            tmin = float(row["TMIN"])
            tmax = float(row["TMAX"])
            irrad = float(row["IRRAD"])
            vap = float(row["VAP"])
            wind = float(row["WIND"])
            rain = float(row["RAIN"])
            et0_ref = float(row.get("ET0", 0))

            # Compute reference ET values and clamp to PCSE trait ranges
            try:
                e0_raw, es0_raw, et0_raw = reference_ET(
                    day, lat, 50.0, tmin, tmax, irrad, vap, wind,
                    ANGSTA=0.25, ANGSTB=0.50,
                )
            except Exception:
                e0_raw, es0_raw, et0_raw = et0_ref * 1.1, et0_ref * 0.9, max(et0_ref, 0.5)
            e0 = max(0.0, min(e0_raw, 2.5))
            es0 = max(0.0, min(es0_raw, 2.5))
            et0 = max(0.0, min(et0_raw, 2.5))

            wdc = WeatherDataContainer(
                LAT=lat, LON=lon, ELEV=50.0,
                DAY=day,
                IRRAD=irrad, TMIN=tmin, TMAX=tmax,
                VAP=vap, RAIN=rain,
                E0=e0, ES0=es0, ET0=et0,
                WIND=wind, TEMP=float(row.get("TEMP", (tmin + tmax) / 2)),
            )
            weather_containers[(day, 0)] = wdc

        weather_provider = WeatherDataProvider()
        weather_provider.store = weather_containers
        weather_provider.latitude = lat
        weather_provider.longitude = lon
        weather_provider.elevation = 50.0
        weather_provider.description = "Custom weather from Open-Meteo"

        # Build agro management as a list of campaigns with a crop calendar
        from datetime import timedelta
        end_estimate = season_start + timedelta(days=min((season_end - season_start).days, 300))
        agro_data = [{
            season_start: {
                "CropCalendar": {
                    "crop_name": yaml_crop_name,
                    "variety_name": yaml_variety,
                    "crop_start_date": sowing_date,
                    "crop_start_type": "sowing",
                    "crop_end_date": None,
                    "crop_end_type": "maturity",
                    "max_duration": max(1, (season_end - season_start).days),
                },
                "TimedEvents": None,
                "StateEvents": None,
            },
        }]

        # Build ParameterProvider from site + soil + crop data
        from pcse.base import ParameterProvider
        soil_params = {
            "SMFCF": soil_data.get("smfc", 0.30),
            "SM0": soil_data.get("s0", 0.40),
            "SMW": soil_data.get("smw", 0.12),
            "CRAIRC": 0.05,
            "K0": 0.01,
            "SOPE": 10.0,
            "KSUB": 1.0,
            "RDMSOL": 0.2,
        }
        params = ParameterProvider(
            sitedata=site,
            soildata=soil_params,
            cropdata=crop_provider,
        )

        wofost = model_cls(params, weather_provider, agro_data)

        # Use the last available weather date as the simulation end date
        sim_end = min(season_end, weather_provider.last_date)
        wofost.run_till(sim_end.isoformat())

        output = wofost.get_output()
        if not output:
            raise ValueError("Empty WOFOST output")

        final = output[-1]
        daily_df = _output_to_dataframe(output)

        yield_kg_ha = final.get("TWSO", 0) * 1000.0

        # If the WOFOST model yields 0 but we have a positive heuristic,
        # log a warning and keep the 0 (user can see the model ran but params need calibration)
        if yield_kg_ha <= 0:
            logger.warning(
                f"WOFOST simulated 0 yield for {crop_label} (crop={yaml_crop_name}, "
                f"variety={yaml_variety}, lat={lat:.1f}). "
                f"Crop parameters likely calibrated for warmer climates."
            )

        biomass_kg_ha = final.get("TAGP", 0) * 1000.0
        peak_lai = max((o.get("LAI") or 0) for o in output)
        transpiration_mm = sum((o.get("TRA") or 0) for o in output)
        precipitation_mm = weather_df["RAIN"].sum()

        result = {
            "resolved_crop": crop_name,
            "resolved_variety": variety,
            "match_type": resolved["match_type"],
            "model": model_name,
            "nutrient_aware": "NWLP" in model_name,
            "yield_kg_ha": yield_kg_ha,
            "total_yield_kg": None,
            "total_yield_tonnes": None,
            "biomass_kg_ha": biomass_kg_ha,
            "peak_lai": peak_lai,
            "water_use_indicators": {
                "transpiration_mm": transpiration_mm,
                "precipitation_mm": precipitation_mm,
                "water_deficit_mm": max(0, transpiration_mm - precipitation_mm),
            },
            "daily": daily_df,
            "fallback_flags": [],
            "confidence": "high",
            "warning": resolved["warning"],
        }
        return result

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.warning(f"WOFOST simulation failed for {crop_label}: {exc}\n{tb}")
        return _heuristic_result(
            crop_label, resolved, lat, lon, season_start, season_end,
            soil_data, parcel_features,
            warning_extras=[str(exc)],
        )


CROP_BASE_YIELDS = {
    "winter wheat": 6000,
    "spring wheat": 5000,
    "winter barley": 5500,
    "spring barley": 4500,
    "oat": 4000,
    "rye": 4500,
    "maize": 8000,
    "potato": 35000,
    "sugar beet": 50000,
    "oilseed rape": 3200,
    "spring oilseed rape": 3000,
    "winter oilseed rape": 3500,
    "pea": 3500,
    "field bean": 3500,
    "grass": 8000,
    "alfalfa": 8000,
    "set-aside": 2000,
}


def _base_yield_for(crop_name: Optional[str]) -> float:
    if crop_name is None:
        return 2000
    crop_lower = crop_name.lower().strip()
    for key, y in CROP_BASE_YIELDS.items():
        if key in crop_lower or crop_lower in key:
            return y
    return 4000


def _heuristic_result(crop_label, resolved, lat, lon, season_start, season_end,
                      soil_data, parcel_features=None, warning_extras=None):
    """Fallback yield estimate when WOFOST is unavailable or fails."""
    warnings = warning_extras or []
    if resolved.get("warning"):
        warnings.append(resolved["warning"])

    crop_name = resolved.get("crop", crop_label)
    days = (season_end - season_start).days or 120
    lat_factor = max(0.5, 1.0 - (abs(lat) - 55) * 0.03)
    season_factor = days / 150.0
    base_yield = _base_yield_for(crop_name)
    yield_kg_ha = base_yield * lat_factor * season_factor

    # NDVI adjustment
    if parcel_features:
        ndvi = parcel_features.get("ndvi")
        if ndvi and ndvi > 0.7:
            yield_kg_ha *= 1.2
        elif ndvi and ndvi < 0.3:
            yield_kg_ha *= 0.5

    return {
        "resolved_crop": crop_name,
        "resolved_variety": resolved.get("variety"),
        "match_type": resolved.get("match_type", "fallback"),
        "model": "heuristic",
        "nutrient_aware": None,
        "yield_kg_ha": yield_kg_ha,
        "total_yield_kg": None,
        "total_yield_tonnes": None,
        "biomass_kg_ha": yield_kg_ha * 2.0,
        "peak_lai": None,
        "water_use_indicators": {
            "transpiration_mm": 200,
            "precipitation_mm": 300,
            "water_deficit_mm": 0,
        },
        "daily": pd.DataFrame(),
        "fallback_flags": ["heuristic"] + (["no_simulation"] if resolved["crop"] is None else []),
        "confidence": "low",
        "warning": "; ".join(w for w in warnings if w),
    }


def _output_to_dataframe(output: list) -> pd.DataFrame:
    """Convert WOFOST output list to DataFrame for daily curves."""
    rows = []
    for o in output:
        day = o.pop("day", None)
        if day is not None:
            o["DAY"] = day
        rows.append(o)
    df = pd.DataFrame(rows)
    if not df.empty and "DAY" in df.columns:
        df["DAY"] = pd.to_datetime(df["DAY"])
        df.set_index("DAY", inplace=True)
    return df


# ── Seed-time defaults for Sweden ────────────────────────────────

SWEDISH_SOWING_DEFAULTS = {
    "winter wheat": date(2024, 9, 15),
    "winter barley": date(2024, 9, 10),
    "winter rye": date(2024, 9, 5),
    "spring wheat": date(2025, 4, 20),
    "spring barley": date(2025, 4, 25),
    "oats": date(2025, 4, 25),
    "maize": date(2025, 5, 5),
    "potato": date(2025, 5, 1),
    "sugar beet": date(2025, 4, 15),
    "oilseed rape": date(2024, 8, 20),
    "spring oilseed rape": date(2025, 4, 15),
    "winter oilseed rape": date(2024, 8, 20),
    "peas": date(2025, 4, 20),
    "field bean": date(2025, 4, 25),
    "grass": date(2024, 4, 15),
}


def sowing_date_for(crop_label: str, season_year: int = 2025) -> date:
    """Return reasonable Swedish sowing date for a crop."""
    resolver = CropResolver()
    resolved = resolver.resolve_crop(crop_label)
    crop = resolved.get("crop", "") or ""
    for key, d in SWEDISH_SOWING_DEFAULTS.items():
        if key in crop:
            return date(season_year, d.month, d.day)
    return date(season_year, 4, 20)
