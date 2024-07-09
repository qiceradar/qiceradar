"""
Dataclasses used for passing rows from the geopackage database around.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class DatabaseGranule:
    """
    This maps a row from the granules table into a class that can be passed around.

    This does largely duplicate a class in download_utig_tdr, but,
    at least for now, I'm intentionall not sharing dependencies between
    the radar_wrangler and plugin repositories.
    """

    # expected to take the format institution_campaign_segment_granule
    granule_name: str
    institution: str
    # database campaign is per-citation (e.g. ICECAP_HiCARS1), and not necessarily
    # how the data is organized in the file system or in QGIS layer tree groups.
    db_campaign: str
    segment: str
    # either "" if dataset doesn't have granule, or "000", "001", etc
    granule: str
    # We only support one product per transect, but there may be multiple
    # different products provided by a given institution.
    # e.g. csarp_standard, csarp_mvdr, 1D_sar, the various UTIG ones...
    product: str
    # e.g. "utig_netcdf", "bas_netcdf", etc. Used to determine whether the
    # plugin supports displaying this granule and for deciding which class
    # to use to load it.
    data_format: str
    # e.g. "wget" (simplest case), "nsidc" (requres nsidc auth), etc
    # Used to determine whether the plugin supports downloading this granule,
    # and deciding which class to use to download it.
    # TODO: Is it possible to have a string enum in a dataclass?
    #  I don't love comparing strings in python code, so would rather
    #  have e.g. if granule.download_method == DatabaseGranule.NSIDC
    download_method: str
    # url used for download
    url: str
    # path (relative to configured root directory) where radargram will be saved
    relative_path: str
    # filesize in bytes of download (if multiple radargrams are zipped together, this
    # is the size of the entire archive, not the single radargram)
    filesize: int


@dataclass
class DatabaseCampaign:
    """
    This maps a row from the campaign table into a class that can be passed around.
    """

    # again, this is the database one, that is NOT how you'd want to display it
    db_campaign: str
    institution: str
    data_citation: str
    science_citation: List[str]
