import pathlib
from typing import Any, Tuple

import h5py
import numpy as np
import scipy.io


def load_radargram(filepath: pathlib.Path) -> Tuple[Any, Any, Any, Any, Any]:
    """
    The available fields change with season, though the core
    variables have been consistent since 2002_Antarctica_P3.

    The biggest difference is whether the .mat file  can
    be opened with h5py, or if we have to use scipy.io
    (This is a function of which version of Matlab was used to create it.)

    Additionally, a single season reported complex radargrams; for
    that one, we display the magnitude.
    """"

    print(f"load_radargram({filepath})")
    try:
        data = h5py.File(filepath, 'r')
        return extract_radargram_h5py(data)
    except OSError:
        print(f"Couldn't open {filepath} with h5py library; trying scipy")

    # Older data needs scipy.io
    data = scipy.io.loadmat(filepath)
    return extract_radargram_scipy(data)



def extract_radargram_h5py(data):
    radargram = data['Data']
    radargram = np.log(np.array(radargram))

    lat = data['Latitude'][:].flatten()
    lon = data['Longitude'][:].flatten()

    utc = data['GPS_time'][:].flatten()
    fast_time_us = 1e6 * data['Time'][:].flatten()
    return radargram, lat, lon, utc, fast_time_us

def extract_radargram_scipy(data):
    """
    Older data needs to be imported using scipy.io.
    """
    radargram = data['Data']
    # 2005_GPRWAIS's data is reported as a complex array
    if np.iscomplexobj(radargram):
        radargram = np.abs(radargram)
    radargram = np.log(np.array(radargram).transpose())

    lat = data['Latitude'].flatten()
    lon = data['Longitude'].flatten()

    utc = data['GPS_time'].flatten()
    fast_time_us = 1e6 * data['Time'].flatten()

    return radargram, lat, lon, utc, fast_time_us