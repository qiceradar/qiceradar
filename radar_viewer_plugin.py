import inspect
import os

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets

from .radar_viewer_widgets import (
    RadarViewerConfigurationWidget,
    # RadarViewerUnavailableWidget,
    # RadarViewerUnsupportedWidget,
    # RadarViewerTransectWidget,
)


class RadarViewerPlugin(QtCore.QObject):
    def __init__(self, iface):
        super(RadarViewerPlugin, self).__init__()
        self.iface = iface
        # TODO: try loading the configuration...
        self.configuration = None

    def initGui(self):
        """
        Required method; called when plugin loaded.
        """
        print("initGui")
        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon = os.path.join(os.path.join(cmd_folder, "airplane.png"))
        self.action = QtWidgets.QAction(
            QtGui.QIcon(icon), "Select and Display Radargrams", self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&Radar Viewer", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """
        Required method; called when plugin unloaded.
        """
        print("unload")
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("&Radar Viewer", self.action)
        del self.action

    def run(self):
        print("run")

        # This kicks off a series of widgets
        # Try to load overall configuration. This will include:
        # * data directory
        # * NSIDC credentials (optional; can be added later)
        # * AAD credentials (likewise optional)
        # if configuration not loaded
        if self.configuration is None:
            cw = RadarViewerConfigurationWidget(self.iface)
            self.configuration = cw.run()

        # QUESTION: What to do here while waiting for a mouse click?
        # On mouse click,
        # sw = RadarViewerSelectionWidget(self.iface)
        # transect = sw.run()

        # if radar_database_utils.is_unavailable(transect):
        #     uw = RadarViewerUnavailableWidget(transect, self.iface)
        #     result = uw.run()
        # elif radar_database_utils.is_unsupported(transect):
        #     uw = RadarViewerUnsupportedWidget(transect, self.iface)
        #     result = uw.run()
        # elif radar_database_utils.is_supported(transect):
        #     # QUESTION: How to keep this alive continuously?
        #     tw = RadarViewerTransectWidget(transect, self.iface)
        #     tw.run()

        # I actually prefer this, because multiple windows are easier to deal
        # with than a dockable window that won't go to the background.
        # self.mainwindow = NuiScalarDataMainWindow(self.iface)
        # self.mainwindow.show()
        # self.mainwindow.run()

        # # However, it's possible to wrap the MainWindow in a DockWidget...
        # mw = NuiScalarDataMainWindow(self.iface)
        # self.dw = QtWidgets.QDockWidget("NUI Scalar Data")
        # # Need to unsubscribe from LCM callbacks when the dock widget is closed.
        # self.dw.closeEvent = lambda event: mw.closeEvent(event)
        # self.dw.setWidget(mw)
        # self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dw)
        # mw.run()

        # print("Done with dockwidget")
        # # This function MUST return, or QGIS will block
