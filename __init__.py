from .radar_viewer_plugin import RadarViewerPlugin


def classFactory(iface):
    return RadarViewerPlugin(iface)
