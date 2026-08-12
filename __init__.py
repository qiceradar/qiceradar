import pathlib
import sys

# We bundle some of our dependencies to get around the mess that it the (lack) # of coherent dependency management across QGIS plugins. The goal is to not
# require users on any OS to pip-install anything.
# For now, this includes:
# * pyfive (pure python replacement to h5py)
external_dir = pathlib.Path(__file__).resolve().parent / "external"
if external_dir not in sys.path:
    sys.path.insert(0, str(external_dir))


def classFactory(iface):
    from .qiceradar_plugin import QIceRadarPlugin

    return QIceRadarPlugin(iface)
