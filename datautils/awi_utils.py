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

# All institution-specific Radargram classes will need to have
# * get_track: returns lat, lon arrays
# * get_trace_times: returns posix time for each trace in radargram
# * get_sample_times: returns time-since-transmission, in us, for each row in radargram
# * .data[::row_skip,::col_skip]
# * set_product(product); since BAS radargrams don't have consistent diensions
#   across products, any caller instantiating this class ALWAYS need to call
#   the above accessors, rather than caching their output.
# QUESTION: Better to take product as an argument? Seems like the
#   path forward for switching between them. However, getting the
#   edge cases right for switching will be a pain, since the arrays are different sizes.


# For now, just using duck typing for the institution-specific radargram classes
class AwiRadargram:
    def __init__(self, filepath: pathlib.Path) -> None:
        pass


# At least for now, we return the data as np.ndarray, which isn't yet
# well supported in mypy.
def load_netcdf(filepath: pathlib.Path) -> Tuple[Any, Any, Any, Any, Any]:
    dd = nc.Dataset(filepath, "r")

    # NOTE: I'm torn on whether to use campaign vs. data fields to make this decision.
    #    I wound up choosing campaign since the presence of PriNumber isn't a good signal
    #    as to which direction interpolation needs to go: FISS2016 uses them for segy, but
    #    in netCDF pulse/chirp are same length with the traces aligned; AGAP has picks
    #    indexed to traces_pulse, and POLARGAP has picks indexed to traces_chirp.
    #    (I guess I could check based on length...)
    #    However, this means that adding new campaigns may require editing code, even if
    #    they're consistent with a previous campaign's format.
    data = np.flipud(dd.variables["WAVEFORM"][:]).transpose()
    utc = dd.variables["TIME"][:]
    lon = dd.variables["LONGITUDE"][:]
    lat = dd.variables["LATITUDE"][:]

    # In microseconds
    fast_time = dd.variables["TWT"][:]

    print(
        f"Loaded AWI radargram. shape = {data.shape}"
    )

    return (data, lat, lon, utc, fast_time)
