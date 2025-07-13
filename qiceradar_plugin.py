# Copyright 2022-2025 Laura Lindzey, UW-APL
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


import enum
import inspect
import os
import pathlib
import sqlite3
import time

# from db_utils import DatabaseGranule, DatabaseCampaign
from typing import Dict, List, Optional, Tuple

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
import PyQt5.QtXml as QtXml

import yaml
from qgis.core import (
    edit,
    Qgis,  # Used for warning levels in the message bar
    QgsFeature,
    QgsGeometry,
    QgsLayerTree,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLineString,
    QgsLineSymbol,
    QgsMapLayer,
    QgsMarkerSymbol,
    QgsMessageLog,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsSpatialIndex,
    QgsSymbol,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgisInterface, QgsDockWidget, QgsMapTool, QgsMapToolPan, QgsMessageBar

from .datautils import db_utils
from .download_widget import DownloadConfirmationDialog, DownloadWindow
from .qiceradar_config import (
    UserConfig,
    nsidc_token_is_valid,
    parse_config,
    rootdir_is_valid,
)
from .qiceradar_config_widget import QIceRadarConfigWidget
from .qiceradar_controls_window import ControlsWindow
from .qiceradar_dialogs import QIceRadarDialogs
from .qiceradar_selection_widget import (
    QIceRadarSelectionTool,
    QIceRadarSelectionWidget,
)
from .qiceradar_symbology_widget import SymbologyWidget
from .datautils import radar_utils
from .radar_viewer_window import RadarWindow


class GranuleMetadata():
    """
    Grab all data about this granule from the layer and the database
    1. layer attributes
    2. granules table
    3. campaign table
    Any logic that requires digging into the layer or the database belongs
    in this class.
    """
    def __init__(self, granule_name, layer_id, feature_id):
        """
        It is too slow to iterate through the whole layer tree looking for
        the matching granule name, so the plugin maintains that mapping
        and provides it as a parameter
        """
        self.granule_name = granule_name

        # dict returned by attributeMap()
        self.layer_attributes = None
        self.db_granule: Optional[db_utils.DatabaseGranule] = None
        self.db_campaign: Optional[db_utils.DatabaseCampaign] = None

        # this includes finding the database file needed for the next call
        self.load_data_from_layer(self.granule_name, layer_id, feature_id)

        # this populates self.db_granule and self.db_campaign
        self.load_data_from_database(self.granule_name, self.database_filepath)

        # TODO: check consistency between layer and databases?
        # TODO: check minimal set a fields have been populated?
        # TODO: confirm this feature is a valid granule before trying to access attributes?
        # if it is not, we probably need to rebuild the index?

    def campaign(self) -> str:
        return self.layer_attributes["campaign"]

    def institution(self) -> str:
        return self.layer_attributes["institution"]

    def radargram_is_available(self) -> bool:
        availability = self.layer_attributes["availability"]
        # Older database versions used u/a/s, rather than just u/a
        return availability != "u"

    def can_download_radargram(self) -> bool:
        try:
            relative_path = feature["relative_path"]
        except Exception as ex:
            relative_path = ""

        try:
            download_method = self.db_granule.download_method
        except Exception as ex:
            download_method = None

        return len(relative_path) >= 0 and download_method in QIceRadarPlugin.supported_download_methods

    def can_view_radargram(self) -> bool:
        try:
            relative_path = feature["relative_path"]
        except Exception as ex:
            relative_path = ""
        valid_path = len(relative_path) >= 0

        try:
            data_format = self.db_granule.data_format
        except Exception as ex:
            data_format = None
        valid_data_format = data_format in radar_utils.RadarData.supported_data_formats

        valid_campaign = self.db_campaign is not None

        return valid_path and valid_data_format and valid_campaign


    @profile
    def load_data_from_layer(self, granule_name: str, layer_id, feature_id):

        # QgsMapLayer is the abstract class; this will *actually* return
        # a QgsVectorLayer which has getFeature() and getFeatures() methods
        # So, add an assert to make mypy happy.
        # TODO: cleanup type annotation handling -- should not use an assert here
        # because user might have added different layer and we need to handle that gracefully

        # assert isinstance(layer, QgsVectorLayer)

        root: QgsLayerTree = QgsProject.instance().layerTreeRoot()
        layer: QgsMapLayer = root.findLayer(layer_id).layer()
        feature = layer.getFeature(feature_id)
        self.layer_attributes = feature.attributeMap()
        self.database_filepath = layer.source().split("|")[0]

    @profile
    def load_data_from_database(self, granule_name: str, database_filepath: str):
        connection = sqlite3.connect(database_filepath)
        cursor = connection.cursor()

        sql_cmd = f"SELECT * FROM granules where name is '{granule_name}'"
        result = cursor.execute(sql_cmd)
        rows = result.fetchall()
        try:
            self.db_granule = db_utils.DatabaseGranule(*rows[0])
        except IndexError as ex:
            QgsMessageLog.logMessage(
                f"Cannot select {granule_name}. Invalid response {rows} from command {sql_cmd}"
            )
        except Exception as ex:
            QgsMessageLog.logMessage(f"Invalid response {rows} from command {sql_cmd}")


        sql_cmd = (
            f"SELECT * FROM campaigns where name is '{self.campaign()}'"
        )
        result = cursor.execute(sql_cmd)
        rows = result.fetchall()
        try:
            self.db_campaign = db_utils.DatabaseCampaign(*rows[0])
        except Exception as ex:
            QgsMessageLog.logMessage(
                f"Invalid response {rows} from command {sql_cmd}"
            )



class QIceRadarPlugin(QtCore.QObject):
    class Operation(enum.IntEnum):
        DOWNLOAD = enum.auto()
        VIEW = enum.auto()

    # TODO: Probably better to get this from the radar_downloader,
    # though right now, they filtering on download methods happens in
    # launch_radar_downloader
    supported_download_methods = ["nsidc", "wget"]


    def __init__(self, iface: QgisInterface) -> None:
        """
        This is called when the plugin is reloaded

        """
        super(QIceRadarPlugin, self).__init__()
        self.iface = iface
        self.message_bar = self.iface.messageBar()

        # Create this here because we try to clean it up on unload
        self.download_dock_widget: Optional[QtWidgets.QDockWidget] = None
        self.download_window: Optional[DownloadWindow] = None

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

        # Try loading config when plugin initialized (before project has been selected)
        self.config = UserConfig()
        try:
            # Save to global QGIS settings, not per-project.
            # If per-project, need to read settings after icon clicked, not when
            # plugin loaded (plugins are loaded before user selects the project.)
            qs = QtCore.QSettings()
            config_str = qs.value("qiceradar_config")
            config_dict = yaml.safe_load(config_str)
            self.config = parse_config(config_dict)
        except Exception as ex:
            QgsMessageLog.logMessage(f"Error loading config: {ex}")

        # Need to wait for project to be opened before actually creating layer group
        self.radar_viewer_group: Optional[QgsLayerTreeGroup] = None

        # need to wait for project with QIceRadar index to be loaded
        # before we can modify the renderers to indicate downloaded transects
        self.index_layers_categorized = False

        self.transect_groups: Dict[str, QgsLayerTreeGroup] = {}
        self.trace_features: Dict[str, QgsFeature] = {}
        self.trace_layers: Dict[str, QgsVectorLayer] = {}
        self.radar_xlim_features: Dict[str, QgsFeature] = {}
        self.radar_xlim_layers: Dict[str, QgsVectorLayer] = {}
        self.segment_features: Dict[str, QgsFeature] = {}
        self.segment_layers: Dict[str, QgsVectorLayer] = {}

    def initGui(self) -> None:
        """
        Required method; also called when plugin loaded.
        """
        QgsMessageLog.logMessage("QIceRadar initGui")
        frame = inspect.currentframe()
        if frame is None:
            errmsg = "Can't find code directory to load icon!"
            QgsMessageLog.logMessage(errmsg)
            # On MacOS, this results in the action text string being the icon
            downloader_icon = QtGui.QIcon()
            viewer_icon = QtGui.QIcon()
        else:
            cmd_folder = os.path.split(inspect.getfile(frame))[0]
            downloader_icon_path = os.path.join(
                cmd_folder, "icons/qiceradar_download.png"
            )
            downloader_icon = QtGui.QIcon(downloader_icon_path)
            viewer_icon_path = os.path.join(
                cmd_folder, "icons/qiceradar_view.png"
            )
            viewer_icon = QtGui.QIcon(viewer_icon_path)

        # This symbology widget needs to be instantiated here, since its
        # signals and slots are tied tightly to the plugin.
        self.symbology_widget = SymbologyWidget(self.iface)

        # hook up signals
        self.symbology_widget.trace_style_changed.connect(self.on_trace_style_changed)
        self.symbology_widget.selected_style_changed.connect(self.on_selected_style_changed)
        self.symbology_widget.segment_style_changed.connect(self.on_segment_style_changed)
        self.symbology_widget.unavailable_line_style_changed.connect(self.on_unavailable_line_style_changed)
        self.symbology_widget.unavailable_point_style_changed.connect(self.on_unavailable_point_style_changed)
        self.symbology_widget.categorized_style_changed.connect(self.on_categorized_style_changed)

        self.controls_window = ControlsWindow(self.symbology_widget)
        self.controls_dock_widget = QgsDockWidget("QIceRadar Controls")
        self.controls_dock_widget.setWidget(self.controls_window)
        self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.controls_dock_widget)
        # If we make it tabified, it tends to get hidden immediately by the log messages
        # self.iface.addTabifiedDockWidget(QtCore.Qt.BottomDockWidgetArea,
        #                                  self.controls_dock_widget,
        #                                  tabifyWith=["PythonConsole"],
        #                                  raiseTab=True)


        # TODO: May want to support a different tooltip in the menu that
        #   launches a GUI where you can either type in a line or select
        #   it from a series of dropdowns, rather than forcing a click.
        # NOTE: We wanted the toolbar icon to appear selected until the MapTool
        #   returns a clicked point, after which the active map tool should revert
        #   to being whatever it was before the qiceradar action was triggered.
        #   Making the actions "checkable" is a bit of a weird fit (it's meant
        #   for ones that are toggleable, like "bold"), but that lets me control
        #   when we turn it back off. Without that, it deselects when the
        #   run_{viewer, downloader} function returns, rather than when the
        #   map tool has been used. Since the action isn't _actually_ toggleable,
        #   also have to connect the map tool's "activate" function to turning
        #   it on (without this, double-clicks on the icon will make it appear
        #   deactivated when it isn't.)
        self.viewer_action = QtWidgets.QAction(
            viewer_icon, "Display Radargrams", self.iface.mainWindow()
        )
        self.viewer_action.setCheckable(True)
        self.iface.addPluginToMenu("Radar Viewer", self.viewer_action)
        self.iface.addToolBarIcon(self.viewer_action)
        self.viewer_action.triggered.connect(self.run_viewer)

        self.downloader_action = QtWidgets.QAction(
            downloader_icon, "Download Radargrams", self.iface.mainWindow()
        )
        self.downloader_action.setCheckable(True)
        self.iface.addPluginToMenu("Radar Downloader", self.downloader_action)
        self.iface.addToolBarIcon(self.downloader_action)
        self.downloader_action.triggered.connect(self.run_downloader)

    def unload(self) -> None:
        """
        Required method; called when plugin unloaded.
        """
        # If we don't deactivate the map tool explicitly, it will remain
        # active and cause an error if the user tries to click on the map
        curr_tool = self.iface.mapCanvas().mapTool()
        if isinstance(curr_tool, QIceRadarSelectionTool):
            self.iface.mapCanvas().unsetMapTool(curr_tool)

        self.iface.removeToolBarIcon(self.viewer_action)
        self.iface.removeToolBarIcon(self.downloader_action)
        self.iface.removePluginMenu("&Radar Viewer", self.viewer_action)
        self.iface.removePluginMenu("&Radar Downloader", self.downloader_action)
        self.iface.removeDockWidget(self.controls_dock_widget)
        del self.viewer_action
        del self.downloader_action
        del self.controls_dock_widget
        if self.download_dock_widget is not None:
            self.iface.removeDockWidget(self.download_dock_widget)
            del self.download_dock_widget

    def set_config(self, config: UserConfig) -> None:
        """
        Callback passed to the QIceRadarConfigWidget to set config
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
        qs = QtCore.QSettings()
        qs.setValue("qiceradar_config", yaml.safe_dump(config_dict))
        # This is how to do it per-project, rather than globally
        # QgsProject.instance().writeEntry(
        #     "radar_viewer", "user_config", yaml.safe_dump(config_dict)
        # )

    def create_radar_viewer_group(self) -> None:
        """
        When QGIS is first started, __init__() and initGui() are called
        before a project is loaded. So, neither one of them is suitable
        as a place to initialize layers for the plugin.

        Instead, each time the viewer plugin is activated, it should call this.
        """
        root = QgsProject.instance().layerTreeRoot()
        # TODO: raise an exception here if root is None? (If it is,
        #   there's nothing the plugin can do.)
        if root is None:
            raise Exception("Unable to retrieve layerTreeRoot; viewer will not work")

        radar_group = root.findGroup("Radar Viewer")
        if radar_group is None:
            self.radar_viewer_group = root.insertGroup(0, "Radar Viewer")
        else:
            self.radar_viewer_group = radar_group

    def on_named_layer_style_changed(self, style_str: str, target_layer_name: str) -> None:
        """
        Change the style for every layer in the radar viewer group with name
        matching the target name.

        TODO: It might be more robust to explicitly keep a list of layers
        that have been created, rather than filtering them on name (which the
        users are able to change)
        """
        if self.radar_viewer_group is None:
            self.create_radar_viewer_group()

        doc = QtXml.QDomDocument()
        doc.setContent(style_str)

        for layer in self.radar_viewer_group.findLayers():
            if layer.layer().name() != target_layer_name:
                continue
            # QgsMessageLog.logMessage(f"Updating style for {layer.parent().name()}")
            result = layer.layer().importNamedStyle(doc)
            layer.layer().triggerRepaint()

    def on_trace_style_changed(self, style_str: str):
        QgsMessageLog.logMessage(f"on_trace_style_changed")
        self.on_named_layer_style_changed(style_str, "Highlighted Trace")

    def on_selected_style_changed(self, style_str: str):
        QgsMessageLog.logMessage(f"on_selected_style_changed")
        self.on_named_layer_style_changed(style_str, "Selected Region")

    def on_segment_style_changed(self, style_str: str):
        QgsMessageLog.logMessage(f"on_segment_style_changed")
        self.on_named_layer_style_changed(style_str, "Full Transect")

    def on_categorized_style_changed(self, style_str: str):
        QgsMessageLog.logMessage(f"on_categorized_style_changed")
        # This update assumes that rule based renderers have already been created,
        # so initialize them if necessary
        if not self.index_layers_categorized:
            self.update_index_layer_renderers()

        doc = QtXml.QDomDocument()
        doc.setContent(style_str)

        index_group = self.find_index_group()
        if index_group is None:
            return
        for layer in index_group.findLayers():
            features = layer.layer().getFeatures()
            try:
                feature = next(features)
            except StopIteration:
                QgsMessageLog.logMessage(f"Could not find features for {layer}")
                continue
            if not self.is_valid_granule_feature(feature):
                continue

            # Only layers with available data will have a rule based renderer
            dest_renderer = layer.layer().renderer()
            if not isinstance(dest_renderer, QgsRuleBasedRenderer):
                # QgsMessageLog.logMessage(f"...skipping {layer.layer().name()}")
                continue

            # Cache filter expressions for the categories.
            # I couldn't figure out how to only grab symbol styles, so copy
            # whole style then restore the filter rules for the renderer.
            download_filter, supported_filter, else_filter = None, None, None
            for rule in dest_renderer.rootRule().children():
                if rule.label() == "Downloaded":
                    download_filter = rule.filterExpression()
                elif rule.label() == "Supported":
                    supported_filter = rule.filterExpression()
                elif rule.label() == "Available":
                    else_filter = rule.filterExpression()

            result = layer.layer().importNamedStyle(doc)

            # Have to grab renderer again, since importing the style changed it.
            dest_renderer = layer.layer().renderer()
            for rule in dest_renderer.rootRule().children():
                if rule.label() == "Downloaded":
                    rule.setFilterExpression(download_filter)
                elif rule.label() == "Supported":
                    rule.setFilterExpression(supported_filter)
                elif rule.label() == "Available":
                    rule.setFilterExpression(else_filter)
            layer.layer().setRenderer(dest_renderer)

            self.iface.layerTreeView().refreshLayerSymbology(layer.layer().id())
            layer.layer().triggerRepaint()


    def on_unavailable_point_style_changed(self, style_str: str):
        self.on_unavailable_layer_style_changed(style_str, QgsWkbTypes.PointGeometry)

    def on_unavailable_line_style_changed(self, style_str: str):
        self.on_unavailable_layer_style_changed(style_str, QgsWkbTypes.LineGeometry)

    # NOTE: I'm unsure about the typing here ... might only be valid for
    #       post-3.30, while I'm using the older types.
    def on_unavailable_layer_style_changed(self, style_str: str, geom_type: QgsWkbTypes.GeometryType) -> None:
        """
        Copy style from the style layer to all layers in the QIceRadar index
        with unavailable data that match the input geometry type.

        This takes a few seconds, but I don't think I can make it any faster
        with the current layer organization, since the bulk of the time is spent
        simply iterating through layers and grabbing the first feature.
        """

        index_group = self.find_index_group()
        if index_group is None:
            return

        doc = QtXml.QDomDocument()
        doc.setContent(style_str)

        for layer in index_group.findLayers():
            features = layer.layer().getFeatures()
            try:
                # All layers created by QIceRadar have a single type of features
                feature = next(features)
            except Exception as ex:
                QgsMessageLog.logMessage(f"could not get layer features")
                continue

            # Check layer is marked unavailable
            if feature["availability"] != "u":
                # QgsMessageLog.logMessage(f"data is available for {layer.name()}")
                continue

            if feature.geometry().type() == geom_type:
                layer.layer().importNamedStyle(doc)
                layer.layer().triggerRepaint()

        # This also seems to be optional, though the cookbook says it should be done.
        self.iface.mapCanvas().refresh()


    def find_index_group(self) -> Optional[QgsLayerTreeGroup]:
        # QgsMessageLog.logMessage("find_index_group")
        root = QgsProject.instance().layerTreeRoot()
        layer_group = None
        for layer_group in root.findGroups():
            if "QIceRadar Index" in layer_group.name():
                index_group = layer_group
                break

        if layer_group is None:
            errmsg = (
                "Could not find index data. \n\n"
                "You may need to drag the QIceRadar .qlr file into QGIS. \n\n"
                "Or, if you renamed the index layer, please revert the name to either "
                "'ANTARCTIC QIceRadarIndex' or 'ARCTIC QIceRadar Index'"
            )
            message_box = QtWidgets.QMessageBox()
            message_box.setText(errmsg)
            message_box.exec()
        return layer_group


    def is_valid_granule_feature(self, feature: QgsFeature):
        attributes = feature.attributeMap()
        for field in [
            "availability",
            "campaign",
            "institution",
            "granule",
            "segment",
            "region",
        ]:
            if field not in attributes:
                return False
        return True

    def build_spatial_index(self) -> None:
        """
        This is slow on my MacBook Pro, but not impossibly so.
        """
        index_group = self.find_index_group()
        if index_group is None:
            return

        QgsMessageLog.logMessage("Building spatial index.")

        # We need to store geometries, otherwise nearest neighbor calculations are done
        # based on bounding boxes and the list of closest transects is nonsensical.
        self.spatial_index = QgsSpatialIndex(QgsSpatialIndex.FlagStoreFeatureGeometries)
        index_id = 0
        for institution_group in index_group.children():
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
                    # QgsVectorLayer subclasses QgsMapLayer; this dance
                    # with isinstance is the only way I've found to make mypy
                    # happy with calling methods only defined by the subclass.
                    campaign_layer: QgsMapLayer = campaign.layer()
                    assert isinstance(campaign_layer, QgsVectorLayer)
                    features = campaign_layer.getFeatures()
                    campaign_layer_validated = False
                    for feature in features:
                        if not campaign_layer_validated:
                            # I'm not sure how valuable this check is; we're assuming
                            # that the first feature is all we need to check (has user
                            # added spurious features to a layer accidentally? If so,
                            # this won't help). The catch-all at the bottom may be enough.
                            valid_layer = self.is_valid_granule_feature(feature)
                            if not valid_layer:
                                QgsMessageLog.logMessage(
                                    f"Feature in layer {campaign} missing expected field; not adding to index."
                                )
                                break
                            campaign_layer_validated = True

                        self.spatial_index_lookup[index_id] = (
                            campaign.layer().id(),
                            feature.id(),
                        )
                        feature_name = feature["name"]
                        assert isinstance(feature_name, str)  # make mypy happy
                        if feature_name in self.transect_name_lookup:
                            # Don't die, but do log a message
                            errmsg = (
                                f"Malformed index layer! {feature_name} appears twice!"
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

    def view_selected_transect(
        self,
        rootdir: pathlib.Path,
        db_granule: db_utils.DatabaseGranule,
        db_campaign: db_utils.DatabaseCampaign,
    ) -> None:
        transect_filepath = pathlib.Path(rootdir, db_granule.relative_path)
        already_downloaded = (
            db_granule.relative_path != ""
        ) and transect_filepath.is_file()

        if already_downloaded:
            # It would probably be more pythonic to just try creating the viewer
            # and catching an error if it's "unsupported"...
            if db_granule.data_format in radar_utils.RadarData.supported_data_formats:
                self.launch_radar_viewer(
                    transect_filepath,
                    db_granule,
                    db_campaign,
                )
            else:
                QIceRadarDialogs.display_cannot_view_dialog(
                    db_granule.granule_name
                )
        else:
            QIceRadarDialogs.display_must_download_dialog(transect_filepath, db_granule.granule_name)

    def download_selected_transect(
        self, rootdir: pathlib.Path, db_granule: db_utils.DatabaseGranule
    ) -> None:
        """
        Actually download selected transect.

        Explicitly passes the root directory because anybody
        calling this method needs to have already confirmed that
        self.user_config is valid and self.user_config.rootdir
        is not None.
        """
        transect_filepath = pathlib.Path(rootdir, db_granule.relative_path)
        already_downloaded = (
            db_granule.relative_path != ""
        ) and transect_filepath.is_file()
        if already_downloaded:
            QIceRadarDialogs.display_already_downloaded_dialog(db_granule.granule_name)
        elif db_granule.download_method not in self.supported_download_methods:
            QIceRadarDialogs.display_cannot_download_dialog(db_granule.granule_name)
        else:
            self.launch_radar_downloader(transect_filepath, db_granule)

    def selected_transect_download_callback(self, granule_name: str) -> None:
        """
        Callback for the QIceRadarSelectionWidget that launches the download
        widget for the chosen transect.
        """
        QgsMessageLog.logMessage(f"selected_transect_download_callback: {granule_name}")
        QgsMessageLog.logMessage(f"rootdir = {self.config.rootdir}")

        layer_id, feature_id = self.transect_name_lookup[granule_name]
        granule_metadata = GranuleMetadata(granule_name, layer_id, feature_id)

        if not granule_metadata.radargram_is_available():
            institution = granule_metadata.institution()
            campaign = granule_metadata.campaign()
            QIceRadarDialogs.display_unavailable_dialog(institution, campaign)
            return

        # Can't download or view radargrams without a valid root data directory
        if not rootdir_is_valid(self.config):
            self.request_user_update_config()
            return

        # TODO: refactor to not reach in and directly use db_granule and db_campaign

        if granule_metadata.can_download_radargram():
            self.download_selected_transect(self.config.rootdir, granule_metadata.db_granule)
        else:
            QIceRadarDialogs.display_cannot_download_dialog(granule_name)


    def selected_transect_view_callback(self, granule_name: str) -> None:
        """
        Callback for the QIceRadarSelectionWidget that launches the viewer
        widget for the chosen transect.
        """
        QgsMessageLog.logMessage(f"selected_transect_view_callback: {granule_name}")
        QgsMessageLog.logMessage(f"rootdir = {self.config.rootdir}")

        layer_id, feature_id = self.transect_name_lookup[granule_name]
        granule_metadata = GranuleMetadata(granule_name, layer_id, feature_id)

        if not granule_metadata.radargram_is_available():
            institution = granule_metadata.institution()
            campaign = granule_metadata.campaign()
            QIceRadarDialogs.display_unavailable_dialog(institution, campaign)
            return

        # Can't download or view radargrams without a valid root data directory
        if not rootdir_is_valid(self.config):
            self.request_user_update_config()
            return

        # TODO: refactor to not reach in and directly use db_granule and db_campaign

        if granule_metadata.can_view_radargram():
            self.view_selected_transect(self.config.rootdir, granule_metadata.db_granule, granule_metadata.db_campaign)
        else:
            QIceRadarDialogs.display_cannot_view_dialog(granule_name)

    def launch_radar_downloader(
        self, dest_filepath: pathlib.Path, db_granule: db_utils.DatabaseGranule
    ) -> None:
        """
        Called once all checks on file existance / support for download
        have finished and we're ready to actually download.
        """
        try:
            dest_filepath.parents[0].mkdir(parents=True, exist_ok=True)
        except Exception as ex:
            # This will be raised if the path exists AND isn't a directory.
            # This is the case for me when I have created a symbolic link
            # to an external drive, but the drive isn't mounted.
            # TODO: Rather than just assuming the user will fix it in the
            #   download step, maybe pop up the config dialog here?
            QgsMessageLog.logMessage(f"Exception encountered in mkdir: {ex}")

        # I really don't like creating headers here, because it exposes
        # the DownloadWorker's implementation details of using requests.
        # Consider refactoring if we wind up with more methods that
        # don't just need additional headers passed to requests.get
        headers = {}
        if db_granule.download_method == "nsidc":
            if not nsidc_token_is_valid(self.config):
                # TODO: I'm experimenting with using the MessageBar
                #  for user updates rather than a bunch of pop-up dialogs.
                #  This mix is probably confusing.
                # TODO: May also want to mention "and an internet connection"
                #   since this warning message will also pop up if we can't connect
                msg = "A valid token is required to download data from NSIDC."

                # QgsMessageBar.pushMessage(msg, level=Qgis.Warning)
                widget = self.message_bar.createMessage("Invalid Config", msg)
                button = QtWidgets.QPushButton(widget)
                button.setText("Update Config")
                button.pressed.connect(self.handle_configure_signal)
                widget.layout().addWidget(button)
                self.message_bar.pushWidget(widget, Qgis.Warning)
                return
            else:
                headers = {"Authorization": f"Bearer {self.config.nsidc_token}"}

        dcd = DownloadConfirmationDialog(
            dest_filepath,
            db_granule.institution,
            db_granule.db_campaign,
            db_granule.granule_name,
            db_granule.download_method,
            db_granule.url,
            db_granule.filesize,
        )
        dcd.configure.connect(self.handle_configure_signal)

        dcd.download_confirmed.connect(
            lambda gg=db_granule.granule_name, url=db_granule.url, fp=dest_filepath, fs=db_granule.filesize, hh=headers: self.start_download(
                gg, url, fp, fs, hh
            )
        )
        dcd.run()

    def launch_radar_viewer(
        self,
        transect_filepath: pathlib.Path,
        db_granule: db_utils.DatabaseGranule,
        db_campaign: db_utils.DatabaseCampaign,
    ) -> None:
        # TODO: This needs to clean up if there's an exception!
        # TODO: (So does the widget! I just tested, and it leaves layers when it is closed!)
        self.setup_qgis_layers(db_granule.granule_name)

        trace_cb = (
            lambda lon, lat, tt=db_granule.granule_name: self.update_trace_callback(
                tt, lon, lat
            )
        )
        selection_cb = (
            lambda pts, tt=db_granule.granule_name: self.update_radar_xlim_callback(
                tt, pts
            )
        )
        rw = RadarWindow(
            transect_filepath,
            db_granule,
            db_campaign,
            parent_xlim_changed_cb=selection_cb,
            parent_cursor_cb=trace_cb,
        )
        points = list(zip(rw.radar_data.lon, rw.radar_data.lat))
        self.update_segment_points(db_granule.granule_name, points)

        # QUESTION: Is storing a dict of dock widgets all I need to do to
        # allow multiple radargrams to be open at once? (In that case, both
        # the quit and the ex button would need to remove and clean up the
        # dock widget. And I would want to initialize them as tabs within
        # the same area...)
        self.dw = QtWidgets.QDockWidget(db_granule.granule_name)
        self.dw.setWidget(rw)
        self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dw)

    def setup_qgis_layers(self, granule_name: str) -> None:
        if self.radar_viewer_group is None:
            raise Exception(
                "Error -- by the time setup_qgis_layers is called, radar_viewer_group should have been created!"
            )

        granule_group = self.radar_viewer_group.findGroup(granule_name)
        if granule_group is None:
            QgsMessageLog.logMessage(f"Could not find existing group for granule: {granule_name}")
            granule_group = self.radar_viewer_group.addGroup(granule_name)
        else:
            QgsMessageLog.logMessage(f"Found existing group for granule: {granule_name}")
        self.transect_groups[granule_name] = granule_group
        self.add_trace_layer(granule_group, granule_name)
        self.add_selected_layer(granule_group, granule_name)
        self.add_segment_layer(granule_group, granule_name)


    def add_trace_layer(self, granule_group: QgsLayerTreeGroup, granule_name: str) -> None:
        # QGIS layer & feature for the single-trace cursor
        trace_layer = None
        for layer_node in granule_group.findLayers():
            if layer_node.layer().name() == "Highlighted Trace":
                trace_layer = layer_node.layer()
                break

        if trace_layer is None:
            QgsMessageLog.logMessage(f"Could not find trace layer")
            trace_uri = "point?crs=epsg:4326"
            trace_layer = QgsVectorLayer(trace_uri, "Highlighted Trace", "memory")
            QgsProject.instance().addMapLayer(trace_layer, False)
            granule_group.addLayer(trace_layer)
        else:
            QgsMessageLog.logMessage(f"Found existing trace layer.")
            # It is easiest to just delete all features and recreate what we need
            with edit(trace_layer):
                trace_layer.deleteFeatures(trace_layer.allFeatureIds())

        qs = QtCore.QSettings()
        style_str = qs.value("qiceradar_config/trace_layer_style", None)
        if style_str is None:
            QgsMessageLog.logMessage(f"Could not find: qiceradar_config/trace_layer_style")
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            result = trace_layer.importNamedStyle(doc)
            if not result:
                QgsMessageLog.logMessage(f"add_trace_layer: {result}")

        trace_feature = QgsFeature()
        # Initialize to the pole, then expect the RadarViewer to update it immediately
        trace_geometry = QgsPoint(0, -90)
        trace_feature.setGeometry(trace_geometry)
        trace_provider = trace_layer.dataProvider()
        trace_provider.addFeature(trace_feature)
        trace_layer.updateExtents()
        self.trace_features[granule_name] = trace_feature
        self.trace_layers[granule_name] = trace_layer

    def add_selected_layer(self, granule_group: QgsLayerTreeGroup, granule_name: str) -> None:
        # Features for the displayed segment.
        selected_layer = None
        for layer_node in granule_group.findLayers():
            if layer_node.layer().name() == "Selected Region":
                selected_layer = layer_node.layer()
                break

        if selected_layer is None:
            QgsMessageLog.logMessage(f"Could not find selection layer")
            selected_uri = "LineString?crs=epsg:4326"
            selected_layer = QgsVectorLayer(selected_uri, "Selected Region", "memory")
            QgsProject.instance().addMapLayer(selected_layer, False)
            granule_group.addLayer(selected_layer)
        else:
            QgsMessageLog.logMessage(f"Found existing selection layer.")
            with edit(selected_layer):
                selected_layer.deleteFeatures(selected_layer.allFeatureIds())

        qs = QtCore.QSettings()
        style_str = qs.value("qiceradar_config/selected_layer_style", None)
        if style_str is None:
            QgsMessageLog.logMessage(f"Could not find: qiceradar_config/selected_layer_style")
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            result = selected_layer.importNamedStyle(doc)
            if not result:
                QgsMessageLog.logMessage(f"add_selected_layer: {result}")

        selected_feature = QgsFeature()
        selected_geometry = QgsLineString([QgsPoint(0, -90)])
        selected_feature.setGeometry(selected_geometry)
        selected_provider = selected_layer.dataProvider()
        selected_provider.addFeature(selected_feature)
        selected_layer.updateExtents()
        self.radar_xlim_features[granule_name] = selected_feature
        self.radar_xlim_layers[granule_name] = selected_layer

    def add_segment_layer(self, granule_group: QgsLayerTreeGroup, granule_name: str) -> None:
        # Finally, feature for the entire transect
        # TODO: How to get the geometry _here_? We should know it
        # at this point, and it won't change. However, all other
        # geometry is provided in one of the callbacks...
        segment_layer = None
        for layer_node in granule_group.findLayers():
            if layer_node.layer().name() == "Full Transect":
                segment_layer = layer_node.layer()
                break

        if segment_layer is None:
            QgsMessageLog.logMessage(f"Could not find full transect layer")
            segment_uri = "LineString?crs=epsg:4326"
            segment_layer = QgsVectorLayer(segment_uri, "Full Transect", "memory")
            QgsProject.instance().addMapLayer(segment_layer, False)
            granule_group.addLayer(segment_layer)
        else:
            QgsMessageLog.logMessage(f"Found existing full transect layer.")
            with edit(segment_layer):
                segment_layer.deleteFeatures(segment_layer.allFeatureIds())
        segment_geometry = QgsLineString([QgsPoint(0, -90)])

        qs = QtCore.QSettings()
        style_str = qs.value("qiceradar_config/segment_layer_style", None)
        if style_str is None:
            QgsMessageLog.logMessage(f"Could not find: qiceradar_config/segment_layer_style")
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            result = segment_layer.importNamedStyle(doc)
            if not result:
                QgsMessageLog.logMessage(f"add_segment_layer: {result}")

        segment_feature = QgsFeature()
        segment_geometry = QgsLineString([QgsPoint(0, -90)])
        segment_feature.setGeometry(segment_geometry)
        segment_provider = segment_layer.dataProvider()
        segment_provider.addFeature(segment_feature)
        segment_layer.updateExtents()

        self.segment_features[granule_name] = segment_feature
        self.segment_layers[granule_name] = segment_layer

    def update_trace_callback(self, transect_name: str, lon: float, lat: float) -> None:
        """
        Change location of the point feature corresponding to the
        crosshairs in the radar viewer window.
        """
        # QgsMessageLog.logMessage(f"update_trace_callback with position: {lon}, {lat}!")
        trace_layer = self.trace_layers[transect_name]
        with edit(trace_layer):
            trace_feature = self.trace_features[transect_name]
            trace_layer.changeGeometry(trace_feature.id(), QgsGeometry(QgsPoint(lon, lat)))
            trace_layer.updateExtents()

    def update_radar_xlim_callback(
        self, transect_name: str, points: List[Tuple[float, float]]
    ) -> None:
        # QgsMessageLog.logMessage(f"update_selected_callback with {len(points)} points!")
        radar_xlim_geometry = QgsGeometry(
            QgsLineString([QgsPoint(lon, lat) for lon, lat in points])
        )
        radar_xlim_layer = self.radar_xlim_layers[transect_name]
        with edit(radar_xlim_layer):
            radar_xlim_feature = self.radar_xlim_features[transect_name]
            radar_xlim_layer.changeGeometry(radar_xlim_feature.id(), radar_xlim_geometry)
            radar_xlim_layer.updateExtents()

    def update_segment_points(
        self, transect_name: str, points: List[Tuple[float, float]]
    ) -> None:
        """
        we have to create the layers before the radargram, because
        the radargram viewer has callbacks to update the layers.
        However, we the easiest way to get layer geometry is from
        the radargram.
        TODO: replace this with using the geometry from the layer that
           was clicked!
        """
        # QgsMessageLog.logMessage(f"update_segment_points with {len(points)} points!")
        segment_geometry = QgsGeometry(
            QgsLineString([QgsPoint(lon, lat) for lon, lat in points])
        )
        segment_layer = self.segment_layers[transect_name]
        with edit(segment_layer):
            segment_feature = self.segment_features[transect_name]
            segment_layer.changeGeometry(segment_feature.id(), segment_geometry)
            segment_layer.updateExtents()

    def selected_download_point_callback(self, point: QgsPoint) -> None:
        op = QIceRadarPlugin.Operation.DOWNLOAD
        self.selected_point_callback(op, point)

    def selected_viewer_point_callback(self, point: QgsPoint) -> None:
        op = QIceRadarPlugin.Operation.VIEW
        self.selected_point_callback(op, point)

    # TODO: This works, but only for one radargram. If we want to support more, should probably keep a list of dock widgets!
    def selected_point_callback(self, operation: Operation, point: QgsPointXY) -> None:
        QgsMessageLog.logMessage(f"selected_point_callback: {point.x()}, {point.y()}")
        QgsMessageLog.logMessage(f"op = {operation} (download = {QIceRadarPlugin.Operation.DOWNLOAD}, view = {QIceRadarPlugin.Operation.VIEW})")

        if self.spatial_index is None:
            errmsg = "Spatial index not created -- bug!!"
            QgsMessageLog.logMessage(errmsg)
            return

        # Requesting 500 features is no slower than requesting 5.
        # (It always seems to take ~0.5 seconds)
        # Try to grab enough that we rarely have an empty list.
        neighbors = self.spatial_index.nearestNeighbor(point, 500)
        neighbor_names: List[str] = []
        root = QgsProject.instance().layerTreeRoot()
        for neighbor in neighbors:
            layer_id, feature_id = self.spatial_index_lookup[neighbor]
            tree_layer = root.findLayer(layer_id)

            # This will happen if the user has deleted and re-imported the
            # index database. In that case, we need to regenerate the
            # spatial index.
            if tree_layer is None:
                # I tried to have this display before, but repaint() didn't work
                # So, it's written in past tense to explain what happened.
                msg = "Spatial index was invalid, and has now been re-computed. Please re-try your selection."
                self.message_bar.pushMessage(msg, level=Qgis.Warning, duration=10)
                # self.iface.mainWindow().repaint()
                self.build_spatial_index()
                self.update_index_layer_renderers()
                return


            # Only offer visible layers to the user
            if not tree_layer.isVisible():
                continue

            # Again, making mypy happy...
            layer: QgsMapLayer = tree_layer.layer()
            assert isinstance(layer, QgsVectorLayer)
            feature = layer.getFeature(feature_id)

            feature_name = feature["name"]  # This returns Optional[object]
            assert isinstance(feature_name, str)  # Again, making mypy happy
            # QgsMessageLog.logMessage(
            #     f"Neighbor: {neighbor}, layer = {layer.id()}, "
            #     f"feature_id = {feature_id}, feature name = {feature_name}"
            #  )
            neighbor_names.append(feature_name)
            # Only need to present the 5 nearest
            if len(neighbor_names) >= 5:
                break

        if len(neighbor_names) == 0:
            msg = "Could not find transect near mouse click."
            self.message_bar.pushMessage("QIceRadar", msg, level=Qgis.Warning, duration=5)
        else:
            selection_widget = QIceRadarSelectionWidget(self.iface, neighbor_names)
            if operation is QIceRadarPlugin.Operation.DOWNLOAD:
                selection_widget.selected_radargram.connect(self.selected_transect_download_callback)
            else:  # operation is QIceRadarPlugin.Operation.VIEW:
                selection_widget.selected_radargram.connect(self.selected_transect_view_callback)

            # Chosen transect is set via callback, rather than direct return value
            selection_widget.run()

    def request_user_update_config(self) -> None:
        msg = "Please enter valid root data directory"
        widget = self.message_bar.createMessage("Invalid Config", msg)
        button = QtWidgets.QPushButton(widget)
        button.setText("Update Config")
        button.pressed.connect(self.handle_configure_signal)
        widget.layout().addWidget(button)
        self.message_bar.pushWidget(widget, Qgis.Warning)

    def handle_configure_signal(self) -> None:
        cw = QIceRadarConfigWidget(self.iface, self.config)
        cw.config_saved.connect(self.set_config)
        cw.run()

    def update_index_layer_renderers(self) -> None:
        """
        We indicate which data has been downloaded by changing the
        renderer to be rule-based, checking whether the file exists.
        """
        index_group = self.find_index_group()
        if index_group is None:
            return

        # Converting the Path object back to string in order to work on windows
        # (Can't use path.join within the filter expression)
        # Otherwise, we were getting D:\RadarData/ANTARCTIC, which doesn't work,
        # while a string with only '/' does work on modern Windows.
        rootdir = str(self.config.rootdir).replace('\\', '/')

        # Iterate through all layers in the group
        for ll in index_group.findLayers():
            # get the QgsMapLayer from the QgsLayerTreeLayer
            layer: QgsMapLayer = ll.layer()
            assert isinstance(layer, QgsVectorLayer)
            features = layer.getFeatures()
            try:
                f0 = next(features)
            except StopIteration:
                # This will happen if there are layers with missing data
                # (I saw it when I accidentally used an incomplete database)
                QgsMessageLog.logMessage(f"Could not find features for {layer}")
                continue
            # Only need to check availability of single features, since all in
            # the layer should be the same.
            if f0["availability"] == "u":
                continue

            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            renderer = QgsRuleBasedRenderer(symbol)

            root_rule = renderer.rootRule()

            dl_rule = root_rule.children()[0].clone()
            dl_rule.setLabel("Downloaded")
            dl_rule.setFilterExpression(
                f"""length("relative_path") > 0 and file_exists('{rootdir}/' + "relative_path")"""
            )
            root_rule.appendChild(dl_rule)

            #  distinction between "a" and "s" in the geopackage database
            supported_rule = root_rule.children()[0].clone()
            supported_rule.setLabel("Supported")
            supported_rule.setFilterExpression(f"""length("relative_path") > 0 and not file_exists('{self.config.rootdir}/' + "relative_path")""")
            root_rule.appendChild(supported_rule)

            else_rule = root_rule.children()[0].clone()
            else_rule.setLabel("Available")
            else_rule.setFilterExpression("ELSE")
            root_rule.appendChild(else_rule)

            root_rule.removeChildAt(0)

            layer.setRenderer(renderer)
            layer.triggerRepaint()  # This causes it to apply + redraw
            ll.setExpanded(False)

        self.index_layers_categorized = True

        # Hacky way to force styles to be updated from the config
        qs = QtCore.QSettings()
        style_str = qs.value("qiceradar_config/categorized_layer_style", None)
        if style_str is not None:
            self.on_categorized_style_changed(style_str)

    def run_downloader(self) -> None:
        QgsMessageLog.logMessage("User clicked run_downloader")
        if not rootdir_is_valid(self.config):
            self.request_user_update_config()
            return
        if self.spatial_index is None:
            self.build_spatial_index()
        if not self.index_layers_categorized:
            self.update_index_layer_renderers()

        download_selection_tool = QIceRadarSelectionTool(self.iface.mapCanvas())
        download_selection_tool.selected_point.connect(
            self.selected_download_point_callback
        )

        # The toolbar icon isn't automatically unchecked when the
        # corresponding action is deactivated.
        download_selection_tool.deactivated.connect(
            lambda ac=self.downloader_action, ch=False: self.maybe_set_action_checked(ac, ch)
        )
        # Repeatedly clicking the toolbar icon will toggle its checked
        # state without deactivating the tooltip. For consistency with
        # the built-in QGIS tools, repeated clicking should have no effect
        # and the tool will remain active.
        download_selection_tool.activated.connect(
            lambda ac=self.downloader_action, ch=True: self.maybe_set_action_checked(ac, ch)
        )

        self.iface.mapCanvas().setMapTool(download_selection_tool)


    def run_viewer(self) -> None:
        QgsMessageLog.logMessage("User clicked run_viewer")

        self.create_radar_viewer_group()

        if not rootdir_is_valid(self.config):
            self.request_user_update_config()
            return

        # Next, make sure the spatial index has been initialized
        # TODO: detect when project changes and re-initialize!
        if self.spatial_index is None:
            self.build_spatial_index()

        if not self.index_layers_categorized:
            self.update_index_layer_renderers()

        # Create a MapTool to select point on map. After this point, it is callback driven.
        viewer_selection_tool = QIceRadarSelectionTool(self.iface.mapCanvas())
        viewer_selection_tool.selected_point.connect(
            self.selected_viewer_point_callback
        )

        self.iface.mapCanvas().setMapTool(viewer_selection_tool)

        viewer_selection_tool.deactivated.connect(
            lambda ac=self.viewer_action, ch=False: self.maybe_set_action_checked(ac, ch)
        )
        viewer_selection_tool.activated.connect(
            lambda ac=self.viewer_action, ch=True: self.maybe_set_action_checked(ac, ch)
        )

    def maybe_set_action_checked(self, action: QtWidgets.QAction, checked: bool) -> None:
        """
        This is only wrapped in a function so we can catch exceptions
        when it is called in response to a signal.
        Some users have gotten this error when first starting the plugin; so
        far as I can tell, it does not correspond to an actual issue.
        (possibly due to some initialization order/timing?)
        """
        try:
            action.setChecked(checked)
        except AttributeError:
            QgsMessageLog.logMessage("could not uncheck action")

    def start_download(
        self, granule: str, url: str, destination_filepath: pathlib.Path, filesize: int, headers: Dict[str, str]
    ) -> None:
        """
        After the confirmation dialog has finished, this section
        actually kicks off the download
        """
        if self.download_dock_widget is None:
            self.download_window = DownloadWindow(self.iface)
            self.download_window.download_finished.connect(
                self.update_index_layer_renderers
            )
            self.download_dock_widget = QgsDockWidget("QIceRadar Downloader")
            self.download_dock_widget.setWidget(self.download_window)
            # self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.download_dock_widget)
            self.iface.addTabifiedDockWidget(QtCore.Qt.BottomDockWidgetArea,
                                         self.download_dock_widget,
                                         tabifyWith=["PythonConsole","MessageLog"],
                                         raiseTab=True)
        # TODO: add downloadTransectWidget to the download window!
        self.download_window.download(granule, url, destination_filepath, filesize, headers)
        # Bring to front again, in case user closed it
        self.download_dock_widget.setUserVisible(True)
