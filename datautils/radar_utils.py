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

import enum
import pathlib
from typing import List

import numpy as np
import pyproj

from . import awi_utils, bas_utils, cresis_utils, db_utils, utig_utils


class Institutions(enum.IntEnum):
    AWI = 0
    BAS = 1
    CRESIS = 2
    KOPRI = 3
    LDEO = 4
    PRIC = 5
    UTIG = 6

class RadarData:
    """
    This is all the radar-specific data, for a given product that has
    been loaded. Includes parameters derived from the data.
    """
    supported_data_formats = ["awi_netcdf", "bas_netcdf", "utig_netcdf", "cresis_mat"]

    # TODO: Refactor this so institution and campaign are enums, and filepath is actually a pathlib.Path
    def __init__(
        self, db_granule: db_utils.DatabaseGranule, filepath: pathlib.Path
    ) -> None:
        # TODO: look this up from institution+campaign?
        self.institution = db_granule.institution
        if db_granule.data_format == "awi_netcdf":
            self.available_products = ["csarp"]
            (
                self.data,  # TODO: rename this to radargram
                self.lat,
                self.lon,
                self.utc,
                self.fast_time_us,
            ) = awi_utils.load_netcdf(filepath)
        elif db_granule.data_format == "bas_netcdf":
            # TODO: consider supporting pulse
            # TODO: Note that the BAS data has campaign embedded, so no need to pass it in.
            self.available_products = ["chirp"]
            # TODO: I'd prefer a function call that directly sets these;
            #   or maybe a BasRadarData.
            (
                self.data,  # TODO: rename this to radargram
                self.lat,
                self.lon,
                self.utc,
                self.fast_time_us,
            ) = bas_utils.load_chirp_data(filepath)
        elif db_granule.data_format == "utig_netcdf":
            # TODO: Add this to the granules database and plumb it through
            #   to radargram
            # TODO: This is no longer true -- it appears that DAY released
            #   GIMBLE as foc1
            self.available_products = ["pik1"]
            (
                self.data,  # TODO: rename this to radargram
                self.lat,
                self.lon,
                self.utc,
                self.fast_time_us,
            ) = utig_utils.load_radargram(filepath)
        elif db_granule.data_format == "cresis_mat":
            # TODO: This should be the actual product. I think the
            #  database needs to include that ...
            self.available_products = ["cresis"]
            try:
                (
                    self.data,  # TODO: rename this to radargram
                    self.lat,
                    self.lon,
                    self.utc,
                    self.fast_time_us,
                ) = cresis_utils.load_radargram(filepath)
            except Exception as ex:
                print(f"Couldn't load {filepath}.")
                raise(ex)
        else:
            raise Exception("Only BAS, CRESIS & UTIG formats supported for now!")

        # elif self.institution == "UTIG":
        #     self.available_products = ["high_gain", "low_gain"]
        #     self.data = radutils.radutils.load_radar_data(
        #         pst, product, channel, filename
        #     )
        # elif self.institution == "CRESIS":
        #     # TODO: What product does CReSIS release to NSIDC?
        #     # I'm assuming standard. Consider mvdr & quicklook.
        #     self.available_products = ["standard"]
        #     self.data = radutils.radutils.load_cresis_data(pst, product, channel)
        # else:
        #     print("WARNING: unrecognized institution")
        #     self.available_products = ["raw"]

        # # TODO: reimplement these!
        # self.rtc = radutils.conversions.RadarTimeConverter(self.pst)
        # self.rpc = radutils.conversions.RadarPositionConverter(self.pst, self.rtc)

        self.num_traces, self.num_samples = self.data.shape
        self.min_val = np.amin(self.data)
        self.max_val = np.amax(self.data)

        # TODO: This needs to use the map's CRS, not hard-coded to Antarctica
        proj = pyproj.Proj("EPSG:3031")
        self.xx, self.yy = proj(self.lon, self.lat)
        self.geod = pyproj.Geod(ellps="WGS84")  # TODO: Better name?

    def along_track_dist(self) -> List[float]:
        """
        Compute along-track distance for every trace in the radargram
        """
        _, _, deltas = self.geod.inv(
            self.lon[1:], self.lat[1:], self.lon[0:-1], self.lat[0:-1]
        )
        dists = [0]
        dists.extend(np.cumsum(deltas))
        return np.array(dists)
