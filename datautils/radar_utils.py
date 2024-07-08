import enum
import pathlib
from typing import List

import numpy as np
import pyproj

from . import bas_utils, db_utils, utig_utils


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

    # TODO: Refactor this so institution and campaign are enums, and filepath is actually a pathlib.Path
    def __init__(
        self, db_granule: db_utils.DatabaseGranule, filepath: pathlib.Path
    ) -> None:
        # TODO: look this up from institution+campaign?
        self.institution = db_granule.institution
        if db_granule.data_format == "bas_netcdf":
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
            self.available_products = ["pik1"]
            (
                self.data,  # TODO: rename this to radargram
                self.lat,
                self.lon,
                self.utc,
                self.fast_time_us,
            ) = utig_utils.load_radargram(filepath)
        else:
            raise Exception("Only BAS & UTIG formats supported for now!")

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
