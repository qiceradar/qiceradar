import inspect
import os
import pathlib
from typing import Dict, Optional, Tuple
import yaml

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets

import qgis.core
from qgis.core import (
    QgsFeature,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsSpatialIndex,
)

import qgis.gui
from qgis.gui import QgsMapTool, QgsMapToolPan

from .radar_viewer_configuration_widget import (
    RadarViewerConfigurationWidget,
)

from .radar_viewer_data_utils import get_granule_filepath

from .radar_viewer_selection_widget import (
    RadarViewerSelectionTool,
    RadarViewerSelectionWidget,
)

from .radar_viewer_radargram_widget import RadarViewerRadargramWidget
from .radar_viewer_download_widget import RadarViewerDownloadWidget

from .radar_viewer_config import UserConfig, parse_config, config_is_valid


class RadarViewerPlugin(QtCore.QObject):
    def __init__(self, iface) -> None:
        super(RadarViewerPlugin, self).__init__()
        self.iface = iface

        # The spatial index needs to be created for each new project
        # TODO: Consider whether to support user switching projects and
        #  thus needing to regenerate the spatial index. (e.g. Arctic / Antarctic switch?)
        self.spatial_index: Optional[QgsSpatialIndex] = None
        # The spatial index only returns the IDs of features.
        # So, if we insert features from multiple layers, it's up to us to do the
        # bookkeeping between spatial index ID and layer ID.
        # This dict maps from the integer ID in the spatial index to
        # (layer_id, feature_id), where:
        # * "layer_id" is the string returned by layer.id()
        # * "feature_id" is the int returned by feature.id(), and can be used
        #    to access the feature via layer.getFeature(feature_id)
        self.spatial_index_lookup: Dict[int, Tuple[str, int]] = {}
        # After presenting the transect names to the user to select among,
        # need to map back to a feature in the database that we can query.
        self.transect_name_lookup: Dict[str, Tuple[str, int]] = {}

        # Cache this when starting the selection tool in order to reset state
        self.prev_map_tool: Optional[QgsMapTool] = None

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

    def initGui(self) -> None:
        """
        Required method; called when plugin loaded.
        """
        print("initGui")
        frame = inspect.currentframe()
        if frame is None:
            errmsg = "Can't find code directory to load icon!"
            QgsMessageLog.logMessage(errmsg)
        else:
            cmd_folder = os.path.split(inspect.getfile(frame))[0]
            icon = os.path.join(os.path.join(cmd_folder, "airplane.png"))

        # TODO: May want to support a different tooltip in the menu that
        #   launches a GUI where you can either type in a line or select
        #   it from a series of dropdowns, rather than forcing a click.
        self.action = QtWidgets.QAction(
            QtGui.QIcon(icon), "Select and Display Radargrams", self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&Radar Viewer", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self) -> None:
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

    def set_config(self, config: UserConfig) -> None:
        """
        Callback passed to the RadarViewerConfigurationWidget to set config
        once it has been validated. (The QDialog class doesn't seem to allow
        returning more complex values, so it needs to be done indirectly.)
        """
        self.config = config
        self.save_config()

    def save_config(self) -> None:
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
            QgsMessageLog.logMessage("Found QIceRadar group!")

        # We need to store geometries, otherwise nearest neighbor calculations are done
        # based on bounding boxes and the list of closest transects is nonsensical.
        self.spatial_index = QgsSpatialIndex(QgsSpatialIndex.FlagStoreFeatureGeometries)
        index_id = 0
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
                    # I think the stub files are wrong; this is flagged as a non-existant method, but it works.
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
                    # QgsMessageLog.logMessage(f"Adding features from {campaign.name()}")
                    for feature in campaign.layer().getFeatures():
                        self.spatial_index_lookup[index_id] = (
                            campaign.layer().id(),
                            feature.id(),
                        )
                        feature_name = feature.attributeMap()["name"]
                        if feature_name in self.transect_name_lookup:
                            # Don't die, but do log a message
                            errmsg = (
                                "Malformed index layer! {feature_name} appears twice!"
                            )
                            QgsMessageLog.logMessage(errmsg)
                        self.transect_name_lookup[feature_name] = (
                            campaign.layer().id(),
                            feature.id(),
                        )
                        new_feature = QgsFeature(feature)
                        new_feature.setId(index_id)
                        index_id += 1
                        self.spatial_index.addFeature(new_feature)

                except Exception as ex:
                    QgsMessageLog.logMessage(f"{repr(ex)}")

    def selected_transect_callback(self, transect_name: str) -> None:
        """
        Callback for the RadarViewerSelectionWidget that launches the appropriate
        UI element for the chosen transect.
        """
        QgsMessageLog.logMessage(f"{transect_name} selected!")
        layer_id, feature_id = self.transect_name_lookup[transect_name]
        # TODO: recover name -> layer + ID, so we can look up info about it

        root = QgsProject.instance().layerTreeRoot()
        layer = root.findLayer(layer_id).layer()
        feature = layer.getFeature(feature_id)

        availability = feature.attributeMap()["availability"]
        institution = feature.attributeMap()["institution"]
        region = feature.attributeMap()["region"]
        campaign = feature.attributeMap()["campaign"]
        segment = feature.attributeMap()["segment"]
        granule = feature.attributeMap()["granule"]
        uri = feature.attributeMap()["uri"]

        if availability == "u":
            # TODO: Consider special case for BEDMAP1?
            msg = (
                "We have not found publicly-available radargrams for this transect."
                "<br><br>"
                f"Institution: {institution}"
                "<br>"
                f"Campaign: {campaign}"
                "<br><br>"
                "If these are now available, please let us know so we can update the database!"
                "<br><br>"
                'Submit an issue: <a href="https://github.com/qiceradar/radar_wrangler/issues/new">https://github.com/qiceradar/radar_wrangler/issues/new</a>'
                "<br>"
                'Or send us email: <a href="mailto:qiceradar@gmail.com">qiceradar@gmail.com</a>'
                "<br><br>"
                "If this is your data and you're thinking about releasing it, feel free to get in touch. We'd love to help if we can."
            )
            message_box = QtWidgets.QMessageBox()
            message_box.setTextFormat(QtCore.Qt.RichText)
            message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            message_box.setText(msg)
            message_box.exec()
            return
        elif availability == "a":
            # TODO: Consider special case for information about Stanford's digitization efforts?
            # TODO: Rather than "available"/"Unavailable", maybe database should
            #   have enum for what format the data IS, and then the code decides
            #   whether it's supported?
            # TODO: This may also be a prompt to update the code itself / present
            #   a link to the page documenting supported formats.
            # TODO: uri needs to be a proper link!
            msg = (
                "These radargrams are available, but their format is not currently supported in the viewer "
                "<br><br>"
                f"Institution: {institution}"
                "<br>"
                f"Campaign: {campaign}"
                "<br>"
                f"Segment: {segment}"
                "<br>"
                f"URI: {uri}"
                "<br><br>"
                "If these are particularly important to your work, let us know! "
                "This feedback will help prioritize future development efforts. "
                "<br><br>"
                'Submit an issue: <a href="https://github.com/qiceradar/radar_viewer/issues/new">https://github.com/qiceradar/radar_viewer/issues/new</a>'
                "<br>"
                'Or send us email: <a href="mailto:qiceradar@gmail.com">qiceradar@gmail.com</a>'
            )
            message_box = QtWidgets.QMessageBox()
            message_box.setTextFormat(QtCore.Qt.RichText)
            message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            message_box.setText(msg)
            message_box.exec()
        elif availability == "s":
            # mypy doesn't recognize the first option as doing the same check, so
            # flags get_granule_filepath as having incompatible arguments.
            # if not config_is_valid(self.config):
            if self.config.rootdir is None:
                QgsMessageLog.logMessage(
                    "Invalid config. Can't download or view radargrams."
                )
                return
            transect_filepath = get_granule_filepath(
                self.config.rootdir, region, institution, campaign, segment, granule
            )
            downloaded = transect_filepath is not None and transect_filepath.is_file()
            if downloaded:
                vw = RadarViewerRadargramWidget()
                vw.run()
                # TODO: user probably wants to immediately open what they've downloaded
            else:
                dw = RadarViewerDownloadWidget(
                    self.config.rootdir, feature.attributeMap()
                )
                dw.run()

    def selected_point_callback(self, point: QgsPointXY) -> None:
        QgsMessageLog.logMessage(f"Got point! {point.x()}, {point.y()}")

        # TODO: Really, if it is None, this should be an error condition.
        if self.prev_map_tool is not None:
            self.iface.mapCanvas().setMapTool(self.prev_map_tool)
            self.prev_map_tool = None

        if self.spatial_index is None:
            errmsg = "Spatial index not created -- bug!!"
            QgsMessageLog.logMessage(errmsg)
            return
        neighbors = self.spatial_index.nearestNeighbor(point, 5)
        neighbor_names = []
        QgsMessageLog.logMessage("Got neighbors!")
        root = QgsProject.instance().layerTreeRoot()
        for neighbor in neighbors:
            layer_id, feature_id = self.spatial_index_lookup[neighbor]
            layer = root.findLayer(layer_id).layer()
            feature = layer.getFeature(feature_id)
            feature_name = feature.attributeMap()["name"]
            QgsMessageLog.logMessage(
                f"Neighbor: {neighbor}, layer = {layer.id()}, "
                f"feature_id = {feature_id}, feature name = {feature_name}"
            )
            neighbor_names.append(feature_name)

        ts = RadarViewerSelectionWidget(
            self.iface, neighbor_names, self.selected_transect_callback
        )
        # Chosen transect is set via callback, rather than direct return value
        ts.run()

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
        # mypy doesn't like this: "expression has type "type[QgsMapToolPan]", variable has type "QgsMapTool | None")"
        self.prev_map_tool = self.iface.mapCanvas().mapTool()
        if self.prev_map_tool is None:
            # mypy doesn't like this; not sure why QgsMapToolPan isn't accepted as a QgsMapTool, which is its base class
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
