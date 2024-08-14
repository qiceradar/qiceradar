def classFactory(iface):
    from .qiceradar_plugin import QIceRadarPlugin
    return QIceRadarPlugin(iface)
