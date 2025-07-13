# Copyright 2022-2025 Laura Lindzey, UW-APL
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import pathlib
from typing import Any, Tuple

import netCDF4 as nc
import numpy as np
import pyproj


def load_radargram(filepath: pathlib.Path) -> Tuple[Any, Any, Any, Any, Any]:
    # Starting with AGASEA, then moving on ...
    dd = nc.Dataset(filepath, "r")

    lon = None
    if "longitude" in dd.variables:
        lon = dd.variables["longitude"][:].data
    elif "lon" in dd.variables:
        lon = dd.variables["lon"][:].data

    lat = None
    if "latitude" in dd.variables:
        lat = dd.variables["latitude"][:].data
    elif "lat" in dd.variables:
        lat = dd.variables["lat"][:].data

    if lat is None or lon is None:
        msg = f"Could not find lon/lat in {filepath}. Vars are {dd.variables.keys()}"
        raise Exception(msg)

    ps71 = pyproj.Proj("epsg:3031")
    xx, yy = ps71(lon, lat)

    # in microseconds
    fast_time_us = None
    if "fast-time" in dd.variables:
        # AGASEA
        fast_time_us = dd.variables["fast-time"][:].data
    elif "fasttime" in dd.variables:
        # EAGLE, OIA, ICECAP, GIMBLE, COLDEX
        fast_time_us = dd.variables["fasttime"][:].data
    else:
        raise Exception(
            f"Could not find fast time data in {filepath}. Vars are: {dd.variables.keys()}"
        )

    utc = None
    # no UTC in AGASEA
    # field 'time' is "seconds since 2016-01-24 00:00:00" for EAGLE, OIA, ICECAP, GIMBLE, COLDEX

    # This changed across surveys
    # AGASEA: 'data_hi_gain', 'fast-time' (no UTC time?)
    radargram = None
    if "data_hi_gain" in dd.variables:
        # AGASEA
        radargram = dd.variables["data_hi_gain"][:].data
    elif "amplitude_hi_gain" in dd.variables:
        # EAGLE
        radargram = dd.variables["amplitude_hi_gain"][:].data
    elif "amplitude_high_gain" in dd.variables:
        # OIA, ICECAP, GIMBLE, COLDEX
        radargram = dd.variables["amplitude_high_gain"][:].data
    else:
        raise Exception(
            f"Could not find radar data in {filepath}. Vars are: {dd.variables.keys()}"
        )

    # UTIG's radargrams are traces x samples; BAS's are samples x traces
    radargram = np.log(radargram)

    return radargram, lat, lon, utc, fast_time_us
