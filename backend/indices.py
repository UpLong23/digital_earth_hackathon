import numpy as np


def ndvi(nir, red):
    return (nir - red) / (nir + red + 1e-10)


def ndre(nir, red_edge):
    return (nir - red_edge) / (nir + red_edge + 1e-10)


def ci_green(nir, green):
    return (nir / (green + 1e-10)) - 1.0


def reip(b05, b06, b07):
    re = 705 + 35 * ((b05 + b07) / 2 - b06) / ((b07 - b05) / 2 + 1e-10) / 2
    return np.clip(re, 670, 780)


def zonal_mean(index_array, mask):
    if mask.sum() == 0:
        return 0.0
    return float(np.nanmean(index_array[mask]))


def compute_ndvi_timeseries(s2_cube, parcel_mask, time_dim="t"):
    import xarray as xr
    red = s2_cube["B04"]
    nir = s2_cube["B08"]
    ndvi_data = ndvi(nir.values, red.values)
    mask_2d = parcel_mask.astype(bool)
    means = []
    for t_idx in range(ndvi_data.shape[0]):
        means.append(zonal_mean(ndvi_data[t_idx], mask_2d))
    return np.array(means)
