import inspect
import os
import yaml

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets

import qgis.core
from qgis.core import QgsMessageLog, QgsProject

from .radar_viewer_widgets import (
    RadarViewerConfigurationWidget,
    # RadarViewerUnavailableWidget,
    # RadarViewerUnsupportedWidget,
    # RadarViewerTransectWidget,
)

from .radar_viewer_config import UserConfig, parse_config, config_is_valid


class RadarViewerPlugin(QtCore.QObject):
    def __init__(self, iface):
        super(RadarViewerPlugin, self).__init__()
        self.iface = iface

        # Default value
        self.config = UserConfig()
        try:
            # Save to global QGIS settings, not per-project.
            # If per-project, need to read settings after icon clicked, not when
            # plugin loaded (plugins are loaded before user selects the project.)
            qs = QtCore.QSettings()
            config_str = qs.value("radar_viewer_config")
            QgsMessageLog.logMessage(f"Tried to load config. config_str = {config_str}")
            config_dict = yaml.safe_load(config_str)
            self.config = parse_config(config_dict)
            print(f"Loaded config! {self.config}")
        except Exception as ex:
            QgsMessageLog.logMessage(f"Error loading config: {ex}")

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

    def load_config(self):
        """
        Load config from project file.
        This needs to be separate from __init__, since plugins are loaded when
        QGIS starts, but the config data is stored in the project directory.
        """
        pass

    def set_config(self, config):
        """
        Callback passed to the RadarViewerConfigurationWidget to set config
        once it has been validated. (The QDialog class doesn't seem to allow
        returning more complex values, so it needs to be done indirectly.)
        """
        self.config = config
        self.save_config()

    def save_config(self):
        # Can't dump a NamedTuple using yaml, so convert to a dict
        config_dict = {key: getattr(self.config, key) for key in self.config._fields}
        if config_dict["rootdir"] is not None:
            config_dict["rootdir"] = str(config_dict["rootdir"])
        QgsMessageLog.logMessage(
            f"Saving updated config! {yaml.safe_dump(config_dict)}"
        )
        qs = QtCore.QSettings()
        qs.setValue("radar_viewer_config", yaml.safe_dump(config_dict))
        # QgsProject.instance().writeEntry(
        #     "radar_viewer", "user_config", yaml.safe_dump(config_dict)
        # )

    def run(self) -> None:
        print("run")

        # This kicks off a series of widgets
        # Try to load overall configuration. This will include:
        # * data directory
        # * NSIDC credentials (optional; can be added later)
        # * AAD credentials (likewise optional)
        # if configuration not loaded
        if self.config is not None and not config_is_valid(self.config):
            cw = RadarViewerConfigurationWidget(
                self.iface, self.config, self.set_config
            )
            cw.run()

        QgsMessageLog.logMessage(f"Config = {self.config}; ready for use!")

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
