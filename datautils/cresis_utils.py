import pathlib
from typing import Any, Tuple

import h5py
import numpy as np
import scipy.io


def load_radargram(filepath: pathlib.Path) -> Tuple[Any, Any, Any, Any, Any]:
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

    lat = np.array(data['Latitude']).flatten()
    lon = np.array(data['Longitude']).flatten()

    utc = np.array(data['GPS_time']).flatten()
    fast_time_us = data['Time'][0] # np.ndarray
    # It also has Elevation, Roll, Pitch, Heading, Surface
    return radargram, lat, lon, utc, fast_time_us

def extract_radargram_scipy(data):
    radargram = data['Data']
    radargram = np.log(np.array(radargram).transpose())

    lat = data['Latitude'][0]
    lon = data['Longitude'][0]

    utc = data['GPS_time'][0]
    fast_time_us = data['Time'][0] # np.ndarray

    # It also has Elevation, Roll, Pitch, Heading, Surface
    return radargram, lat, lon, utc, fast_time_us