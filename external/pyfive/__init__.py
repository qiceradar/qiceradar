"""
pyfive : a pure python HDF5 file reader.
This is the public API exposed by pyfive,
which is a small subset of the H5PY API.
"""

from pyfive.high_level import File, Group, Dataset
from pyfive.h5t import (
    check_enum_dtype,
    check_string_dtype,
    check_dtype,
    opaque_dtype,
    check_opaque_dtype,
)
from pyfive.h5py import Datatype, Empty
from importlib.metadata import version
from pyfive.inspect import p5ncdump

from importlib.metadata import PackageNotFoundError

try:
    __version__ = version("pyfive")
except PackageNotFoundError:
    __version__ = "unknown"
