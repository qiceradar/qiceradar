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

# from db_utils import DatabaseGranule, DatabaseCampaign
from typing import Dict, List, Optional, Tuple

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
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
)
from qgis.gui import QgisInterface, QgsMapTool, QgsMapToolPan, QgsMessageBar

from .datautils import db_utils
from .download_widget import DownloadConfirmationDialog, DownloadWindow
from .qiceradar_config import (
    UserConfig,
    nsidc_token_is_valid,
    parse_config,
    rootdir_is_valid,
)
from .qiceradar_config_widget import QIceRadarConfigWidget
from .qiceradar_selection_widget import (
    QIceRadarSelectionTool,
    QIceRadarSelectionWidget,
)
from .radar_viewer_window import RadarWindow


class QIceRadarPlugin(QtCore.QObject):
    class Operation(enum.IntEnum):
        DOWNLOAD = enum.auto()
        VIEW = enum.auto()

    def __init__(self, iface: QgisInterface) -> None:
        """
        This is called when the plugin is reloaded

        """
        super(QIceRadarPlugin, self).__init__()
        self.iface = iface
        self.message_bar = self.iface.messageBar()

        # TODO: Probably better to get this from the radar_viewer / radar_downloader
        self.supported_data_formats = ["awi_netcdf", "bas_netcdf", "utig_netcdf", "cresis_mat"]
        self.supported_download_methods = ["nsidc", "wget"]

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

        # For now, these layers go in the main layer tree, so we have to wait
        # to initialize it.
        self.symbology_group: Optional[QgsLayerTreeGroup] = None
        self.style_layers: Dict[str, QgsMapLayer] = {}
        self.symbology_group_initialized = False

        # Similarly, need to wait for project with QIceRadar index to be loaded
        # before we can modify the renderers to indicate downloaded transects
        self.download_renderer_added = False

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
                os.path.join(cmd_folder, "icons/qiceradar_download.png")
            )
            downloader_icon = QtGui.QIcon(downloader_icon_path)
            viewer_icon_path = os.path.join(
                os.path.join(cmd_folder, "icons/qiceradar_view.png")
            )
            viewer_icon = QtGui.QIcon(viewer_icon_path)

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
        # active and cause an error if the user tries to click
        curr_tool = self.iface.mapCanvas().mapTool()
        if isinstance(curr_tool, QIceRadarSelectionTool):
            self.iface.mapCanvas().unsetMapTool(curr_tool)

        try:
            self.style_layers["trace"].styleChanged.disconnect(self.update_trace_layer_style)
            self.style_layers["selected"].styleChanged.disconnect(self.update_selected_layer_style)
            self.style_layers["segment"].styleChanged.disconnect(self.update_segment_layer_style)
        except KeyError:
            # If the plugin is reloaded before the style layers have been
            # initialized, we expect a KeyError
            pass
        except Exception as ex:
            QgsMessageLog.logMessage(f"unexpected exception when disconnecting style changed callback: {ex}, type={type(ex)}")

        self.iface.removeToolBarIcon(self.viewer_action)
        self.iface.removeToolBarIcon(self.downloader_action)
        self.iface.removePluginMenu("&Radar Viewer", self.viewer_action)
        self.iface.removePluginMenu("&Radar Downloader", self.downloader_action)
        del self.viewer_action
        del self.downloader_action

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

    def create_symbology_group(self) -> None:
        """
        Create group containing dummy layers for each of the symbols
        the user might want to style.

        Attach callbacks to these dummy layers that then set the style
        indicating status of layers in the index or extent of currently
        viewed radargram.

        TODO: consider moving this out of the main layer tree and into a
        dock widget with other QIceRadar controls.

        For now, we're saving the style via the layer styling in the project,
        which means we have to initialize after the project is loaded...
        It might be cleaner to do so via QSettings, since:
        * we don't currently detect that the layers have changed and update
          our pointers to them
        * it is confusing that the callbacks aren't attached until the user has
          clicked one of the QIceRadar actions.
        """
        QgsMessageLog.logMessage(f"create_symbology_group")
        if self.symbology_group_initialized:
            return

        root = QgsProject.instance().layerTreeRoot()
        if root is None:
            raise Exception("Unable to retrieve layerTreeRoot; viewer will not work")

        symbology_group_name = "QIceRadar Symbology"
        symbology_group = root.findGroup(symbology_group_name)
        if symbology_group is None:
            self.symbology_group = root.insertGroup(0, symbology_group_name)
        else:
            self.symbology_group = symbology_group

        # TODO: add layers!

        # QGIS layer & feature for the single-trace cursor
        trace_layer = None
        for layer_node in symbology_group.findLayers():
            if layer_node.layer().name() == "Highlighted Trace":
                trace_layer = layer_node.layer()
                break

        if trace_layer is not None:
            # Leave the existing layer as-is; use its saved styling.
            QgsMessageLog.logMessage(f"Found existing trace layer.")
        else:
            QgsMessageLog.logMessage(f"Could not find trace layer")
            trace_symbol = QgsMarkerSymbol.createSimple(
                {
                    "name": "circle",
                    "color": QtGui.QColor.fromRgb(255, 255, 0, 255),
                    "size": "10",
                    "size_unit": "Point",
                }
            )
            trace_uri = "point?crs=epsg:4326"
            trace_layer = QgsVectorLayer(trace_uri, "Highlighted Trace", "memory")
            trace_layer.renderer().setSymbol(trace_symbol)
            QgsProject.instance().addMapLayer(trace_layer, False)
            symbology_group.addLayer(trace_layer)


        # QUESTION: do we even need to add a symbol?
        # trace_feature = QgsFeature()
        # trace_geometry = QgsPoint(0, -90)
        # trace_feature.setGeometry(trace_geometry)
        # trace_provider = trace_layer.dataProvider()
        # trace_provider.addFeature(trace_feature)
        # trace_layer.updateExtents()
        self.style_layers["trace"]  = trace_layer

        # Features for the displayed segment.
        selected_layer = None
        for layer_node in symbology_group.findLayers():
            if layer_node.layer().name() == "Selected Region":
                selected_layer = layer_node.layer()
                break

        if selected_layer is not None:
            QgsMessageLog.logMessage(f"Found existing selection layer.")
        else:
            QgsMessageLog.logMessage(f"Could not find selection layer")
            selected_symbol = QgsLineSymbol.createSimple(
                {
                    "color": QtGui.QColor.fromRgb(255, 128, 30, 255),
                    "line_width": 2,
                    "line_width_units": "Point",
                }
            )
            selected_uri = "LineString?crs=epsg:4326"
            selected_layer = QgsVectorLayer(selected_uri, "Selected Region", "memory")
            selected_layer.renderer().setSymbol(selected_symbol)
            QgsProject.instance().addMapLayer(selected_layer, False)
            symbology_group.addLayer(selected_layer)

        self.style_layers["selected"]  = selected_layer

        # Finally, feature for the entire transect
        segment_layer = None
        for layer_node in symbology_group.findLayers():
            if layer_node.layer().name() == "Full Transect":
                segment_layer = layer_node.layer()
                break

        if segment_layer is not None:
            QgsMessageLog.logMessage(f"Found existing full transect layer.")
        else:
            QgsMessageLog.logMessage(f"Could not find full transect layer")
            segment_symbol = QgsLineSymbol.createSimple(
                {
                    "color": QtGui.QColor.fromRgb(255, 0, 0, 255),
                    "line_width": 1,
                    "line_width_units": "Point",
                }
            )
            segment_uri = "LineString?crs=epsg:4326"
            segment_layer = QgsVectorLayer(segment_uri, "Full Transect", "memory")
            segment_layer.renderer().setSymbol(segment_symbol)
            QgsProject.instance().addMapLayer(segment_layer, False)
            symbology_group.addLayer(segment_layer)

        self.style_layers["segment"]  = segment_layer

        # This is called *twice* when the user clicks "Apply" or "OK" in the layer properties dialog; I haven't yet figured out why.
        # Using 3 very similar functions rather than lambdas since we need
        # to pass the function as an argument to disconnect.
        self.style_layers["trace"].styleChanged.connect(self.update_trace_layer_style)
        self.style_layers["selected"].styleChanged.connect(self.update_selected_layer_style)
        self.style_layers["segment"].styleChanged.connect(self.update_segment_layer_style)

        self.symbology_group_initialized = True

    def copy_layer_style(self, source_layer, target_layer):
        # copied from https://gis.stackexchange.com/questions/444905/copying-layer-styles-using-pyqgis
        style_name = source_layer.styleManager().currentStyle()
        style = source_layer.styleManager().style(style_name)

        # addStyle will not override a style name, so remove it first
        target_layer.styleManager().removeStyle('copied')
        target_layer.styleManager().addStyle('copied', style)
        target_layer.styleManager().setCurrentStyle('copied')
        target_layer.triggerRepaint()
        target_layer.emitStyleChanged()

    def update_trace_layer_style(self):
        QgsMessageLog.logMessage(f"Trace layer style changed")
        # Iterate over QgsLayerTreeLayers in the group
        for layer in self.radar_viewer_group.findLayers():
            if layer.layer().name() != "Highlighted Trace":
                continue
            QgsMessageLog.logMessage(f"Updating trace style for {layer.parent().name()}!")
            self.copy_layer_style(self.style_layers["trace"], layer.layer())

    def update_selected_layer_style(self):
        QgsMessageLog.logMessage(f"Selected layer style changed")
        for layer in self.radar_viewer_group.findLayers():
            if layer.layer().name() != "Selected Region":
                continue
            QgsMessageLog.logMessage(f"Updating selected region style for {layer.parent().name()}!")
            self.copy_layer_style(self.style_layers["selected"], layer.layer())

    def update_segment_layer_style(self):
        QgsMessageLog.logMessage(f"Segment layer style changed")
        for layer in self.radar_viewer_group.findLayers():
            if layer.layer().name() != "Full Transect":
                continue
            QgsMessageLog.logMessage(f"Updating full segment style for {layer.parent().name()}!")
            self.copy_layer_style(self.style_layers["segment"], layer.layer())

    def build_spatial_index(self) -> None:
        """
        This is slow on my MacBook Pro, but not impossibly so.
        """
        QgsMessageLog.logMessage("Building spatial index.")
        root = QgsProject.instance().layerTreeRoot()
        qiceradar_group = root.findGroup("ANTARCTIC QIceRadar Index")
        if qiceradar_group is None:
            qiceradar_group = root.findGroup("ARCTIC QIceRadar Index")
        if qiceradar_group is None:
            errmsg = (
                "Could not find index data. \n\n"
                "You may need to drag the QIceRadar .qlr file into QGIS. \n\n"
                "Or, if you renamed the index layer, please revert the name to either "
                "'ANTARCTIC QIceRadarIndex' or 'ARCTIC QIceRadar Index'"
            )
            message_box = QtWidgets.QMessageBox()
            message_box.setText(errmsg)
            message_box.exec()
            return

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
                    # QgsVectorLayer subclasses QgsMapLayer; this dance
                    # with isinstance is the only way I've found to make mypy
                    # happy with calling methods only defined by the subclass.
                    campaign_layer: QgsMapLayer = campaign.layer()
                    assert isinstance(campaign_layer, QgsVectorLayer)
                    feat = next(campaign_layer.getFeatures())
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
                    for feature in campaign_layer.getFeatures():
                        self.spatial_index_lookup[index_id] = (
                            campaign.layer().id(),
                            feature.id(),
                        )
                        feature_name = feature.attributeMap()["name"]
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

    def display_unavailable_dialog(self, institution: str, campaign: str) -> None:
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
            'Submit an issue: <a href="https://github.com/qiceradar/qiceradar/issues/new">https://github.com/qiceradar/qiceradar/issues/new</a>'
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

    def display_unsupported_download_method_dialog(self, granule_name: str) -> None:
        msg = (
            "This radargram is available, but we are not able to assist with downloading it."
            "<br><br>"
            f"Granule: {granule_name}"
            "<br><br>"
            "If this campaign is particularly important to your work, let us know! "
            "This feedback will help prioritize future development efforts. "
            "<br><br>"
            'Submit an issue: <a href="https://github.com/qiceradar/qiceradar/issues/new">https://github.com/qiceradar/qiceradar/issues/new</a>'
            "<br>"
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    def display_unsupported_data_format_dialog(self, granule_name: str) -> None:
        # TODO: Consider special case for information about Stanford's digitization efforts?
        # TODO: This may also be a prompt to update the code itself / present
        #   a link to the page documenting supported formats.
        msg = (
            "This radargram is available, but its format is not currently supported in the viewer "
            "<br><br>"
            f"Granule: {granule_name}"
            "<br><br>"
            "If this campaign is particularly important to your work, let us know! "
            "This feedback will help prioritize future development efforts. "
            "<br><br>"
            'Submit an issue: <a href="https://github.com/qiceradar/qiceradar/issues/new">https://github.com/qiceradar/qiceradar/issues/new</a>'
            "<br>"
            'Or send us an email: <a href="mailto:qiceradar@gmail.com">qiceradar@gmail.com</a>'
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    def display_already_downloaded_dialog(
        self, db_granule: db_utils.DatabaseGranule
    ) -> None:
        # TODO: Should make this impossible by filtering the selection
        #   based on un-downloaded transects.
        #   I *could* make the unavailable impossible, but I want to display info
        #   about them, and a 3rd tooltip doesn't make sense.
        msg = (
            "Already downloaded requested data!"
            "<br>"
            f"Granule: {db_granule.granule_name}"
            "<br>"
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    def display_must_download_dialog(
        self, radargram_filepath: pathlib.Path, db_granule: db_utils.DatabaseGranule
    ) -> None:
        msg = (
            "Must download radargram before viewing it"
            "<br>"
            f"Granule: {db_granule.granule_name}"
            "<br>"
            f"(Looking for data in: {radargram_filepath})"
            "<br>"
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

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
            if db_granule.data_format in self.supported_data_formats:
                self.launch_radar_viewer(
                    transect_filepath,
                    db_granule,
                    db_campaign,
                )
            else:
                self.display_unsupported_data_format_dialog(
                    db_granule.granule_name
                )
        else:
            self.display_must_download_dialog(transect_filepath, db_granule)

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
            self.display_already_downloaded_dialog(db_granule)
        elif db_granule.download_method not in self.supported_download_methods:
            self.display_unsupported_download_method_dialog(db_granule.granule_name)
        else:
            self.launch_radar_downloader(transect_filepath, db_granule)

    def selected_transect_callback(
        self, operation: Operation, transect_name: str
    ) -> None:
        """
        Callback for the QIceRadarSelectionWidget that launches the appropriate
        widget (download, viewer) for the chosen transect.
        They share a callback because there is a common set of checks before
        either QIceRadar widget can be run.
        """
        QgsMessageLog.logMessage(f"selected_transect_callback: {transect_name}")
        QgsMessageLog.logMessage(f"op = {operation} (download = {QIceRadarPlugin.Operation.DOWNLOAD}, view = {QIceRadarPlugin.Operation.VIEW})")
        QgsMessageLog.logMessage(f"rootdir = {self.config.rootdir}")

        layer_id, feature_id = self.transect_name_lookup[transect_name]

        root: QgsLayerTree = QgsProject.instance().layerTreeRoot()
        # QgsMapLayer is the abstract class; this will *actually* return
        # a QgsVectorLayer which has getFeature() and getFeatures() methods
        # So, add an assert to make mypy happy.
        layer: QgsMapLayer = root.findLayer(layer_id).layer()
        assert isinstance(layer, QgsVectorLayer)
        feature = layer.getFeature(feature_id)
        granule_name = feature.attributeMap()["name"]

        # mypy doesn't recognize the first option as doing the same check, so
        # flags get_granule_filepath as having incompatible arguments.
        # if not rootdir_is_valid(self.config):
        if self.config.rootdir is None:
            QgsMessageLog.logMessage(
                "Invalid config. Can't download or view radargrams."
            )
            return

        # The viewer/downloader widgets need information from the gpkg
        # database that also provided the geometry information for this
        # layer.
        database_file = layer.source().split("|")[0]
        connection = sqlite3.connect(database_file)
        cursor = connection.cursor()

        sql_cmd = f"SELECT * FROM granules where name is '{granule_name}'"
        result = cursor.execute(sql_cmd)
        rows = result.fetchall()
        try:
            db_granule = db_utils.DatabaseGranule(*rows[0])
        except IndexError as ex:
            QgsMessageLog.logMessage(
                f"Cannot select {granule_name}. Invalid response {rows} from command {sql_cmd}"
            )
            db_granule = None
        except Exception as ex:
            QgsMessageLog.logMessage(f"Invalid response {rows} from command {sql_cmd}")
            db_granule = None

        if db_granule is not None:
            sql_cmd = (
                f"SELECT * FROM campaigns where name is '{db_granule.db_campaign}'"
            )
            result = cursor.execute(sql_cmd)
            rows = result.fetchall()
            try:
                db_campaign = db_utils.DatabaseCampaign(*rows[0])
            except Exception as ex:
                QgsMessageLog.logMessage(
                    f"Invalid response {rows} from command {sql_cmd}"
                )
                db_campaign = None

        connection.close()

        if db_granule is None:
            availability = feature.attributeMap()["availability"]
            if availability == "u":
                institution = feature.attributeMap()["institution"]
                campaign = feature.attributeMap()["campaign"]
                self.display_unavailable_dialog(institution, campaign)
            else:
                # TODO: This is a bit confusing -- if db_granule is None,
                #  we don't have any info about it in the database, so
                #  I'm not sure splitting it out into download_method /
                #  data_format is the fundamental thing, since we don't
                #  even know what the method or format should be!
                #  There are also cases where I expect to provide a link
                #  but direct the user to download it manually.
                if operation == QIceRadarPlugin.Operation.DOWNLOAD:
                    self.display_unsupported_download_method_dialog(granule_name)
                elif operation == QIceRadarPlugin.Operation.VIEW:
                    self.display_unsupported_data_format_dialog(granule_name)
        else:
            if operation == QIceRadarPlugin.Operation.DOWNLOAD:
                self.download_selected_transect(self.config.rootdir, db_granule)
            elif operation == QIceRadarPlugin.Operation.VIEW:
                if db_campaign is None:
                    raise Exception(
                        f"Unable to look up campaign data for {granule_name}"
                    )
                self.view_selected_transect(
                    self.config.rootdir, db_granule, db_campaign
                )

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

        self.dw = QtWidgets.QDockWidget(db_granule.granule_name)
        self.dw.setWidget(rw)
        self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dw)

    def setup_qgis_layers(self, transect_name: str) -> None:
        if self.radar_viewer_group is None:
            raise Exception(
                "Error -- by the time setup_qgis_layers is called, radar_viewer_group should have been created!"
            )

        transect_group = self.radar_viewer_group.findGroup(transect_name)
        if transect_group is None:
            QgsMessageLog.logMessage(f"Could not find existing group for granule: {transect_name}")
            transect_group = self.radar_viewer_group.addGroup(transect_name)
        else:
            QgsMessageLog.logMessage(f"Found existing group for granule: {transect_name}")
        self.transect_groups[transect_name] = transect_group

        # QGIS layer & feature for the single-trace cursor
        trace_layer = None
        for layer_node in transect_group.findLayers():
            if layer_node.layer().name() == "Highlighted Trace":
                trace_layer = layer_node.layer()
                break

        if trace_layer is None:
            QgsMessageLog.logMessage(f"Could not find trace layer")
            trace_uri = "point?crs=epsg:4326"
            trace_layer = QgsVectorLayer(trace_uri, "Highlighted Trace", "memory")
            self.copy_layer_style(self.style_layers["trace"], trace_layer)
            QgsProject.instance().addMapLayer(trace_layer, False)
            transect_group.addLayer(trace_layer)
        else:
            QgsMessageLog.logMessage(f"Found existing trace layer.")
            # It is easiest to just delete all features and recreate what we need
            with edit(trace_layer):
                trace_layer.deleteFeatures(trace_layer.allFeatureIds())

        trace_feature = QgsFeature()
        # Initialize to the pole, then expect the RadarViewer to update it immediately
        trace_geometry = QgsPoint(0, -90)
        trace_feature.setGeometry(trace_geometry)
        trace_provider = trace_layer.dataProvider()
        trace_provider.addFeature(trace_feature)
        trace_layer.updateExtents()
        self.trace_features[transect_name] = trace_feature
        self.trace_layers[transect_name] = trace_layer

        # Features for the displayed segment.
        selected_layer = None
        for layer_node in transect_group.findLayers():
            if layer_node.layer().name() == "Selected Region":
                selected_layer = layer_node.layer()
                break

        if selected_layer is None:
            QgsMessageLog.logMessage(f"Could not find selection layer")
            selected_uri = "LineString?crs=epsg:4326"
            selected_layer = QgsVectorLayer(selected_uri, "Selected Region", "memory")
            self.copy_layer_style(self.style_layers["selected"], selected_layer)
            QgsProject.instance().addMapLayer(selected_layer, False)
            transect_group.addLayer(selected_layer)
        else:
            QgsMessageLog.logMessage(f"Found existing selection layer.")
            with edit(selected_layer):
                selected_layer.deleteFeatures(selected_layer.allFeatureIds())

        selected_feature = QgsFeature()
        selected_geometry = QgsLineString([QgsPoint(0, -90)])
        selected_feature.setGeometry(selected_geometry)
        selected_provider = selected_layer.dataProvider()
        selected_provider.addFeature(selected_feature)
        selected_layer.updateExtents()
        self.radar_xlim_features[transect_name] = selected_feature
        self.radar_xlim_layers[transect_name] = selected_layer

        # Finally, feature for the entire transect
        # TODO: How to get the geometry _here_? We should know it
        # at this point, and it won't change. However, all other
        # geometry is provided in one of the callbacks...
        segment_layer = None
        for layer_node in transect_group.findLayers():
            if layer_node.layer().name() == "Full Transect":
                segment_layer = layer_node.layer()
                break

        if segment_layer is None:
            QgsMessageLog.logMessage(f"Could not find full transect layer")
            segment_uri = "LineString?crs=epsg:4326"
            segment_layer = QgsVectorLayer(segment_uri, "Full Transect", "memory")
            self.copy_layer_style(self.style_layers["segment"], segment_layer)
            QgsProject.instance().addMapLayer(segment_layer, False)
            transect_group.addLayer(segment_layer)
        else:
            QgsMessageLog.logMessage(f"Found existing full transect layer.")
            with edit(segment_layer):
                segment_layer.deleteFeatures(segment_layer.allFeatureIds())
        segment_geometry = QgsLineString([QgsPoint(0, -90)])

        segment_feature = QgsFeature()
        segment_geometry = QgsLineString([QgsPoint(0, -90)])
        segment_feature.setGeometry(segment_geometry)
        segment_provider = segment_layer.dataProvider()
        segment_provider.addFeature(segment_feature)
        segment_layer.updateExtents()

        self.segment_features[transect_name] = segment_feature
        self.segment_layers[transect_name] = segment_layer

    def update_trace_callback(self, transect_name: str, lon: float, lat: float) -> None:
        """
        Change location of the point feature corresponding to the
        crosshairs in the radar viewer window.
        """
        # QgsMessageLog.logMessage(f"update_trace_callback with position: {lon}, {lat}!")
        trace_layer = self.trace_layers[transect_name]
        trace_layer.startEditing()
        trace_feature = self.trace_features[transect_name]
        trace_layer.changeGeometry(trace_feature.id(), QgsGeometry(QgsPoint(lon, lat)))
        trace_layer.commitChanges()

    def update_radar_xlim_callback(
        self, transect_name: str, points: List[Tuple[float, float]]
    ) -> None:
        # QgsMessageLog.logMessage(f"update_selected_callback with {len(points)} points!")
        # To change the location of the displayed feature:
        radar_xlim_geometry = QgsGeometry(
            QgsLineString([QgsPoint(lon, lat) for lon, lat in points])
        )
        radar_xlim_layer = self.radar_xlim_layers[transect_name]
        radar_xlim_layer.startEditing()
        radar_xlim_feature = self.radar_xlim_features[transect_name]
        radar_xlim_layer.changeGeometry(radar_xlim_feature.id(), radar_xlim_geometry)
        radar_xlim_layer.commitChanges()

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
        segment_layer.startEditing()
        segment_feature = self.segment_features[transect_name]
        segment_layer.changeGeometry(segment_feature.id(), segment_geometry)
        segment_layer.commitChanges()

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
                self.update_download_renderer()
                return


            # Only offer visible layers to the user
            if not tree_layer.isVisible():
                continue

            # Again, making mypy happy...
            layer: QgsMapLayer = tree_layer.layer()
            assert isinstance(layer, QgsVectorLayer)
            feature = layer.getFeature(feature_id)

            feature_name = feature.attributeMap()[
                "name"
            ]  # This returns Optional[object]
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
            selection_widget.selected_radargram.connect(
                lambda transect, op=operation: self.selected_transect_callback(op, transect)
            )
            # Chosen transect is set via callback, rather than direct return value
            selection_widget.run()

    def ensure_valid_rootdir(self) -> bool:
        # First, make sure we at least have the root data directory configured
        if not rootdir_is_valid(self.config):
            msg = "Please enter valid root data directory"
            widget = self.message_bar.createMessage("Invalid Config", msg)
            button = QtWidgets.QPushButton(widget)
            button.setText("Update Config")
            button.pressed.connect(self.handle_configure_signal)
            widget.layout().addWidget(button)
            self.message_bar.pushWidget(widget, Qgis.Warning)
            return False
        return True

    def handle_configure_signal(self) -> None:
        cw = QIceRadarConfigWidget(self.iface, self.config)
        cw.config_saved.connect(self.set_config)
        cw.run()

    def update_download_renderer(self) -> None:
        """
        We indicate which data has been downloaded by changing the
        renderer to be rule-based, checking whether the file exists.
        """
        # This is copied from building the spatial index
        root = QgsProject.instance().layerTreeRoot()
        qiceradar_group = root.findGroup("ANTARCTIC QIceRadar Index")
        if qiceradar_group is None:
            qiceradar_group = root.findGroup("ARCTIC QIceRadar Index")
        if qiceradar_group is None:
            errmsg = (
                "Could not find index data. \n\n"
                "You may need to drag the QIceRadar .qlr file into QGIS. \n\n"
                "Or, if you renamed the index layer, please revert the name to either "
                "'ANTARCTIC QIceRadarIndex' or 'ARCTIC QIceRadar Index'"
            )
            message_box = QtWidgets.QMessageBox()
            message_box.setText(errmsg)
            message_box.exec()
            return

        # Iterate through all layers in the group
        for ll in qiceradar_group.findLayers():
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
            # the layer will be the same.
            if f0.attributeMap()["availability"] == "u":
                continue

            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            renderer = QgsRuleBasedRenderer(symbol)

            root_rule = renderer.rootRule()

            # TODO: For now, this will only work for BAS data! making
            #  it work for everybody will require having relative filepaths
            #  in the campaign tables (otherwise, I'd be reconstructing it
            #  here in a campaign-specific way. Ugh.)
            dl_rule = root_rule.children()[0].clone()
            dl_rule.setLabel("Downloaded")
            region = f0.attributeMap()["region"]
            assert isinstance(region, str)  # Make mypy happy; region is an Optional
            region = region.upper()
            institution = f0.attributeMap()["institution"]
            campaign = f0.attributeMap()["campaign"]

            # Converting the Path object back to string in order to work on windows
            # (Can't use path.join within the filter expression)
            # Otherwise, we were getting D:\RadarData/ANTARCTIC, which doesn't work,
            # while a string with only '/' does work on modern Windows.
            rootdir = str(self.config.rootdir).replace('\\', '/')
            dl_rule.setFilterExpression(
                f"""length("relative_path") > 0 and file_exists('{rootdir}/' + "relative_path")"""
            )
            dl_rule.symbol().setWidth(0.35) # Make them more visible
            dl_rule.symbol().setColor(QtGui.QColor(133, 54, 229, 255))
            root_rule.appendChild(dl_rule)

            # TODO: add additional "supported" rule here, and remove the
            #  distinction between "a" and "s" in the geopackage database
            supported_rule = root_rule.children()[0].clone()
            supported_rule.setLabel("Supported")
            supported_rule.setFilterExpression(f"""length("relative_path") > 0 and not file_exists('{self.config.rootdir}/' + "relative_path")""")
            supported_rule.symbol().setColor(QtGui.QColor(31, 120, 180, 255))
            root_rule.appendChild(supported_rule)

            else_rule = root_rule.children()[0].clone()
            else_rule.setLabel("Available")
            else_rule.setFilterExpression("ELSE")
            else_rule.symbol().setColor(QtGui.QColor(68, 68, 68, 255))
            root_rule.appendChild(else_rule)

            root_rule.removeChildAt(0)

            layer.setRenderer(renderer)
            layer.triggerRepaint()  # This causes it to apply + redraw
            ll.setExpanded(False)

        self.download_renderer_added = True

    def run_downloader(self) -> None:
        QgsMessageLog.logMessage("User clicked run_downloader")
        if not self.ensure_valid_rootdir():
            QgsMessageLog.logMessage("...config dir is not valid!")
            return
        if self.spatial_index is None:
            self.build_spatial_index()
        if not self.download_renderer_added:
            self.update_download_renderer()

        self.create_symbology_group()

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
        self.create_symbology_group()

        if not self.ensure_valid_rootdir():
            return

        # Next, make sure the spatial index has been initialized
        # TODO: detect when project changes and re-initialize!
        if self.spatial_index is None:
            self.build_spatial_index()

        if not self.download_renderer_added:
            self.update_download_renderer()

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
        if self.download_window is None:
            self.download_window = DownloadWindow(self.iface)
            self.download_window.download_finished.connect(
                self.update_download_renderer
            )
            self.dock_widget = QtWidgets.QDockWidget("QIceRadar Downloader")
            self.dock_widget.setWidget(self.download_window)
            # TODO: Figure out how to handle the user closing the dock widget
            self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dock_widget)
        # TODO: add downloadTransectWidget to the download window!
        self.download_window.download(granule, url, destination_filepath, filesize, headers)
