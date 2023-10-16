import inspect
import os
import yaml

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets

import qgis.core
from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
    QgsSpatialIndex,
)

import qgis.gui
from qgis.gui import QgsMapToolPan

from .radar_viewer_configuration_widget import (
    RadarViewerConfigurationWidget,
)
from .radar_viewer_selection_widget import (
    RadarViewerSelectionTool,
    RadarViewerSelectionWidget,
)

# RadarViewerUnavailableWidget,
# RadarViewerUnsupportedWidget,
# RadarViewerTransectWidget,

from .radar_viewer_config import UserConfig, parse_config, config_is_valid


class RadarViewerPlugin(QtCore.QObject):
    def __init__(self, iface):
        super(RadarViewerPlugin, self).__init__()
        self.iface = iface

        # The spatial index needs to be created for each new project
        # TODO: Consider whether to support user switching projects and
        #  thus needing to regenerate the spatial index. (e.g. Arctic / Antarctic switch?)
        self.spatial_index = None

        # Cache this when starting the selection tool in order to reset state
        self.prev_map_tool = None
        # Will hold most recently selected map point, for finding nearest transects
        self.selected_point = None

        # Try loading config when plugin initialized (before project has been selected)
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
        # This is how to do it per-project, rather than globally
        # QgsProject.instance().writeEntry(
        #     "radar_viewer", "user_config", yaml.safe_dump(config_dict)
        # )

    def build_spatial_index(self) -> None:
        """
        This is slow on my MacBook Pro, but not impossibly so.
        """
        QgsMessageLog.logMessage("Trying to build spatial index")
        root = QgsProject.instance().layerTreeRoot()
        qiceradar_group = root.findGroup("ANTARCTIC QIceRadar Index")
        if qiceradar_group is None:
            qiceradar_group = root.findGroup("ARCTIC QIceRadar Index")
        if qiceradar_group is None:
            errmsg = (
                "Could not find index data. \n\n"
                "You may need to drag the QIceRadar .qlr file into QGIS. \n\n"
                "Or, if you renamed the index layer, please revert the name to either "
                "'ANTARCTIC QIceRadarIndex' or 'ARCTIC QIceRadar Index' \n\n"
                "Making the group selectable is an existing TODO."
            )
            message_box = QtWidgets.QMessageBox()
            message_box.setText(errmsg)
            message_box.exec()
            return
        else:
            QgsMessageLog.logMessage(f"Found QIceRadar group!")

        self.spatial_index = QgsSpatialIndex()
        for institution_group in qiceradar_group.children():
            if not isinstance(institution_group, QgsLayerTreeGroup):
                # Really, there shouldn't be any, but who knows what layers the user may have added.
                QgsMessageLog.logMessage(
                    f"Unepected layer in QIceRadarIndex: {institution_group}"
                )
                continue
            for campaign in institution_group.children():
                if not isinstance(campaign, QgsLayerTreeLayer):
                    QgsMessageLog.logMessage(
                        f"Unexpected group in QIceRadarIndex{campaign}"
                    )
                    continue
                # Quick sanity check that this is a layer for the index
                try:
                    feat = next(campaign.layer().getFeatures())
                    # TODO: Would be better to have a proper function for checking this.
                    for field in [
                        "availability",
                        "campaign",
                        "institution",
                        "granule",
                        "segment",
                        "region",
                    ]:
                        if field not in feat.attributeMap():
                            QgsMessageLog.logMessage(
                                f"Layer in {campaign} missing expected field {field}; not adding features to index."
                            )
                            break
                    QgsMessageLog.logMessage(f"Adding features from {campaign.name()}")
                    self.spatial_index.addFeatures(campaign.layer().getFeatures())
                except Exception as ex:
                    QgsMessageLog(f"{ex.what()}")

    def selected_point_callback(self, point) -> None:
        self.selected_point = point
        QgsMessageLog.logMessage(f"Got point! {point.x()}, {point.y()}")

        # TODO: Really, if it is None, this should be an error condition.
        if self.prev_map_tool is not None:
            self.iface.mapCanvas().setMapTool(self.prev_map_tool)
            self.prev_map_tool = None

        # TODO: look into setting the StoreFeatureGeometries flag.
        # https://qgis.org/pyqgis/3.22/core/QgsSpatialIndex.html#qgis.core.QgsSpatialIndex.nearestNeighbor
        # "If this QgsSpatialIndex object was not constructed with the FlagStoreFeatureGeometries flag, then the nearest neighbor test is performed based on the feature bounding boxes ONLY, so for non-point geometry features this method is not guaranteed to return the actual closest neighbors.""
        # However, that might be tricky, because this documentation:
        # https://qgis.org/pyqgis/3.22/core/QgsSpatialIndex.html#qgis.core.QgsSpatialIndex.addFeature
        # says that flags are ignored. Huh.

        # TODO: UGGGGH. This only returns the feature ID. And that's only unique
        #  per-layer, not per-project. So I'll have to be more careful about this.
        neighbors = self.spatial_index.nearestNeighbor(point, 5)
        QgsMessageLog.logMessage("Got neighbors!")
        for neighbor in neighbors:
            QgsMessageLog.logMessage(f"Neighbor: {neighbor}, type = {type(neighbor)}")

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

    def run(self) -> None:
        QgsMessageLog.logMessage("run")
        # The QIceRadar tool is a series of widgets, kicked off by clicking on the icon.

        # First, make sure we at least have the root data directory configured
        if not config_is_valid(self.config):
            cw = RadarViewerConfigurationWidget(
                self.iface, self.config, self.set_config
            )
            # Config is set via callback, rather than direct return value
            cw.run()

        if not config_is_valid(self.config):
            QgsMessageLog.logMessage("Invalid configuration; can't start QIceRadar")
            return
        else:
            QgsMessageLog.logMessage(f"Config = {self.config}; ready for use!")

        # Next, make sure the spatial index has been initialized
        # TODO: detect when project changes and re-initialize!
        if self.spatial_index is None:
            self.build_spatial_index()

        # Create a MapTool to select point on map. After this point, it is callback driven.
        # TODO: This feels like something that should be handled in the SelectionTool,
        #  not in the plugin
        self.prev_map_tool = self.iface.mapCanvas().mapTool()
        if self.prev_map_tool is None:
            self.prev_map_tool = QgsMapToolPan
        selection_tool = RadarViewerSelectionTool(
            self.iface.mapCanvas(), self.selected_point_callback
        )
        self.iface.mapCanvas().setMapTool(selection_tool)

        # TODO: It seems that the icon no longer shows as active at this point,
        #  when really, I'd rather it be active while the selection tool is active.

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
