import pathlib
from typing import Any, Tuple

import netCDF4 as nc
import numpy as np
import pyproj


def load_radargram(filepath: pathlib.Path) -> Tuple[Any, Any, Any, Any, Any]:
    # Starting with AGASEA, then moving on ...
    dd = nc.Dataset(filepath, "r")

    lon = None
    if 'longitude' in dd.variables:
        lon = dd.variables['longitude'][:].data
    elif 'lon' in dd.variables:
        lon = dd.variables['lon'][:].data

    lat = None
    if 'latitude' in dd.variables:
        lat = dd.variables['latitude'][:].data
    elif 'lat' in dd.variables:
        lat = dd.variables['lat'][:].data

    if lat is None or lon is None:
        msg = f"Could not find lon/lat in {filepath}. Vars are {dd.variables.keys()}"
        raise Exception(msg)

    ps71 = pyproj.Proj('epsg:3031')
    xx, yy = ps71(lon, lat)

    # in microseconds
    fast_time_us = None
    if "fast-time" in dd.variables:
        fast_time_us = dd.variables["fast-time"][:].data  # AGASEA
    elif "fasttime" in dd.variables:
        fast_time_us = dd.variables["fasttime"][:].data # EAGLE, OIA, ICECAP, GIMBLE, COLDEX
    else:
        raise Exception(f"Could not find fast time data in {filepath}. Vars are: {dd.variables.keys()}")

    utc = None
    # no UTC in AGASEA
    # field 'time' is "seconds since 2016-01-24 00:00:00" for EAGLE, OIA, ICECAP, GIMBLE, COLDEX


    # This changed across surveys
    # AGASEA: 'data_hi_gain', 'fast-time' (no UTC time?)
    radargram = None
    if "data_hi_gain" in dd.variables:
        radargram = dd.variables["data_hi_gain"][:].data # AGASEA
    elif "amplitude_hi_gain" in dd.variables:
        radargram = dd.variables["amplitude_hi_gain"][:].data # EAGLE
    elif "amplitude_high_gain" in dd.variables:
        radargram = dd.variables["amplitude_high_gain"][:].data # OIA, ICECAP, GIMBLE, COLDEX
    else:
        raise Exception(f"Could not find radar data in {filepath}. Vars are: {dd.variables.keys()}")

    # UTIG's radargrams are traces x samples; BAS's are samples x traces
    radargram = np.log(radargram)

    return radargram, lat, lon, utc, fast_time_us