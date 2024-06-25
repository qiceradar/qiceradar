from .qiceradar_plugin import QIceRadarPlugin


def classFactory(iface):
    return QIceRadarPlugin(iface)
