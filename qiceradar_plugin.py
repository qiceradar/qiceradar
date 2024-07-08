import enum
import inspect
import os
import pathlib
import sqlite3
from typing import Dict, List, Optional, Tuple

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
import yaml
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLineString,
    QgsLineSymbol,
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
from qgis.gui import QgsMapTool, QgsMapToolPan

from .download_widget import DownloadConfirmationDialog, DownloadWindow
from .qiceradar_config import UserConfig, config_is_valid, parse_config
from .qiceradar_config_widget import QIceRadarConfigWidget
from .qiceradar_selection_widget import (
    QIceRadarSelectionTool,
    QIceRadarSelectionWidget,
)
from .radar_viewer_data_utils import get_granule_filepath
from .radar_viewer_window import BasicRadarWindow as RadarWindow


class QIceRadarPlugin(QtCore.QObject):
    class Operation(enum.IntEnum):
        DOWNLOAD = enum.auto()
        VIEW = enum.auto()

    def __init__(self, iface) -> None:
        """
        This is called when the plugin is reloaded
        """
        super(QIceRadarPlugin, self).__init__()
        QgsMessageLog.logMessage("QIceRadarPlugin.__init__")
        self.iface = iface
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

        # Cache this when starting the selection tool in order to reset state
        self.prev_map_tool: Optional[QgsMapTool] = None

        # Try loading config when plugin initialized (before project has been selected)
        self.config = UserConfig()
        try:
            # Save to global QGIS settings, not per-project.
            # If per-project, need to read settings after icon clicked, not when
            # plugin loaded (plugins are loaded before user selects the project.)
            qs = QtCore.QSettings()
            config_str = qs.value("qiceradar_config")
            QgsMessageLog.logMessage(f"Tried to load config. config_str = {config_str}")
            config_dict = yaml.safe_load(config_str)
            self.config = parse_config(config_dict)
            print(f"Loaded config! {self.config}")
        except Exception as ex:
            QgsMessageLog.logMessage(f"Error loading config: {ex}")

        # Need to wait for project to be opened before actually creating layer group
        self.radar_viewer_group = None
        # Similarly, need to wait for project with QIceRadar index to be loaded
        # before we can modify the renderers to indicate downloaded transects
        self.download_renderer_added = False

        self.transect_groups: dict[str, QgsLayerTreeGroup] = {}
        self.trace_features: dict[str, QgsFeature] = {}
        self.trace_layers: dict[str, QgsVectorLayer] = {}
        self.radar_xlim_features: dict[str, QgsFeature] = {}
        self.radar_xlim_layers: dict[str, QgsVectorLayer] = {}
        self.segment_features: dict[str, QgsFeature] = {}
        self.segment_layers: dict[str, QgsVectorLayer] = {}

    def initGui(self) -> None:
        """
        Required method; also called when plugin loaded.
        """
        QgsMessageLog.logMessage("initGui")
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
                os.path.join(cmd_folder, "img/icons.001.png")
            )
            downloader_icon = QtGui.QIcon(downloader_icon_path)
            viewer_icon_path = os.path.join(
                os.path.join(cmd_folder, "img/icons.002.png")
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
        self.viewer_action.triggered.connect(self.run_viewer)
        self.iface.addPluginToMenu("Radar Viewer", self.viewer_action)
        self.iface.addToolBarIcon(self.viewer_action)

        self.downloader_action = QtWidgets.QAction(
            downloader_icon, "Download Radargrams", self.iface.mainWindow()
        )
        self.downloader_action.setCheckable(True)
        self.downloader_action.triggered.connect(self.run_downloader)
        self.iface.addPluginToMenu("Radar Downloader", self.downloader_action)
        self.iface.addToolBarIcon(self.downloader_action)

    def unload(self) -> None:
        """
        Required method; called when plugin unloaded.
        """
        QgsMessageLog.logMessage("QIceRadarPlugin.unload")
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
        QgsMessageLog.logMessage(
            "QIceRadarPlugin.set_config. "
            f"Input rootdir = {config.rootdir} "
            f"self.config.rootdir = {self.config.rootdir}"
        )

    def save_config(self) -> None:
        # Can't dump a NamedTuple using yaml, so convert to a dict
        config_dict = {key: getattr(self.config, key) for key in self.config._fields}
        if config_dict["rootdir"] is not None:
            config_dict["rootdir"] = str(config_dict["rootdir"])
        QgsMessageLog.logMessage(
            f"Saving updated config! {yaml.safe_dump(config_dict)}"
        )
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
                "'ANTARCTIC QIceRadarIndex' or 'ARCTIC QIceRadar Index'"
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

    def selected_transect_callback(
        self, operation: Operation, transect_name: str
    ) -> None:
        """
        Callback for the QIceRadarSelectionWidget that launches the appropriate
        widget (download, viewer) for the chosen transect.
        """
        QgsMessageLog.logMessage(f"{transect_name} selected!")
        layer_id, feature_id = self.transect_name_lookup[transect_name]

        root = QgsProject.instance().layerTreeRoot()
        layer = root.findLayer(layer_id).layer()
        feature = layer.getFeature(feature_id)

        # The viewer/downloader widgets need information from the gpkg
        # database that also provided the geometry information for this
        # layer.
        database_file = layer.source().split("|")[0]

        availability = feature.attributeMap()["availability"]
        institution = feature.attributeMap()["institution"]
        region = feature.attributeMap()["region"]
        campaign = feature.attributeMap()["campaign"]
        segment = feature.attributeMap()["segment"]
        granule = feature.attributeMap()["granule"]
        uri = feature.attributeMap()["uri"]
        granule_name = feature.attributeMap()["name"]
        relative_path = feature.attributeMap()["relative_path"]

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
                'Submit an issue: <a href="https://github.com/qiceradar/qiceradar_plugin/issues/new">https://github.com/qiceradar/qiceradar_plugin/issues/new</a>'
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
                'Or send us an email: <a href="mailto:qiceradar@gmail.com">qiceradar@gmail.com</a>'
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
            transect_filepath = pathlib.Path(
                self.config.rootdir, relative_path
            )
            downloaded = transect_filepath is not None and transect_filepath.is_file()
            if downloaded:
                if operation == QIceRadarPlugin.Operation.DOWNLOAD:
                    # TODO: Should make this impossible by filtering the selection
                    #   based on un-downloaded transects.
                    #   I *could* make the unavailable impossible, but I want to display info
                    #   about them, and a 3rd tooltip doesn't make sense.
                    msg = (
                        "Already downloaded transect!"
                        "<br>"
                        f"Institution: {institution}"
                        "<br>"
                        f"Campaign: {campaign}"
                        "<br>"
                        f"Segment: {segment}"
                        "<br>"
                    )
                    message_box = QtWidgets.QMessageBox()
                    message_box.setTextFormat(QtCore.Qt.RichText)
                    message_box.setTextInteractionFlags(
                        QtCore.Qt.TextBrowserInteraction
                    )
                    message_box.setText(msg)
                    message_box.exec()

                else: # operation == VIEW
                    # TODO: This needs to clean up if there's an exception!
                    # TODO: (So does the widget! I just tested, and it leaves layers when it is closed!)
                    self.setup_qgis_layers(transect_name)

                    # Also, my NUI plugin had a "cleanup" step where it unsubscribed to LCM callbacks.
                    # I'm not sure if something similar is necessary here,
                    # or if we can let the user just close the window.
                    # (We probably want to clean up the entries in the layers panel!)

                    trace_cb = (
                        lambda lon, lat, tt=transect_name: self.update_trace_callback(
                            tt, lon, lat
                        )
                    )
                    selection_cb = (
                        lambda pts, tt=transect_name: self.update_radar_xlim_callback(
                            tt, pts
                        )
                    )
                    rw = RadarWindow(
                        institution,
                        campaign,
                        transect_filepath,
                        granule,
                        database_file,
                        parent_xlim_changed_cb=selection_cb,
                        parent_cursor_cb=trace_cb,
                    )
                    points = list(zip(rw.radar_data.lon, rw.radar_data.lat))
                    self.update_segment_points(transect_name, points)

                    self.dw = QtWidgets.QDockWidget(transect_name)
                    self.dw.setWidget(rw)
                    self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dw)
            else:
                if operation == QIceRadarPlugin.Operation.DOWNLOAD:
                    connection = sqlite3.connect(database_file)
                    cursor = connection.cursor()
                    # TODO: Constructing the granule_name like this is problematic;
                    #   it should be passed around as the identifier.
                    sql_cmd = f"SELECT * FROM granules where name = '{granule_name}'"
                    result = cursor.execute(sql_cmd)
                    rows = result.fetchall()
                    connection.close()
                    # QUESTION: How do I want to log this? I need to figure out how these errors
                    #    will propagate through the system.
                    # TODO: I dislike this; setting to None requires checking for None later,
                    #   rather than handling/propagating it right here.
                    try:
                        (
                            db_granule_name,
                            institution,
                            db_campaign,
                            segment,
                            granule,
                            product,
                            _data_format,
                            download_method,
                            url,
                            destination_path,
                            filesize,
                        ) = rows[0]
                    except:
                        QgsMessageLog.logMessage(
                            f"Invalid response {rows} from command {sql_cmd}"
                        )
                        (
                            _data_format,
                            download_method,
                            url,
                            destination_path,
                            filesize,
                        ) = None, None, None, None, None

                    self.granule_filepath = pathlib.Path(
                        self.config.rootdir, destination_path
                    )
                    try:
                        QgsMessageLog.logMessage(f"Creating directory: {self.granule_filepath.parents[0]}")
                        self.granule_filepath.parents[0].mkdir(parents=True, exist_ok=True)
                    except Exception as ex:
                        QgsMessageLog.logMessage(f"Exception encountered in mkdir: {ex}")

                    dcd = DownloadConfirmationDialog(
                        self.config,
                        institution,
                        campaign,
                        db_granule_name,
                        download_method,
                        url,
                        destination_path,
                        filesize,
                    )
                    dcd.configure.connect(self.handle_configure_signal)

                    dcd.download_confirmed.connect(
                        lambda gg=db_granule_name,
                        url=url,
                        fp=transect_filepath,
                        fs=filesize: self.start_download(gg, url, fp, fs)
                    )
                    dcd.run()
                else:
                    # TODO: This should be made impossible -- only offer already-downloaded
                    #  transects to the viewer selection tooltip.
                    msg = (
                        "Must download transect before viewing it"
                        "<br>"
                        f"Institution: {institution}"
                        "<br>"
                        f"Campaign: {campaign}"
                        "<br>"
                        f"Segment: {segment}"
                        "<br>"
                        f"(Looking for data in: {transect_filepath})"
                        "<br>"
                    )
                    message_box = QtWidgets.QMessageBox()
                    message_box.setTextFormat(QtCore.Qt.RichText)
                    message_box.setTextInteractionFlags(
                        QtCore.Qt.TextBrowserInteraction
                    )
                    message_box.setText(msg)
                    message_box.exec()

    def setup_qgis_layers(self, transect_name: str) -> None:
        transect_group = self.radar_viewer_group.addGroup(transect_name)

        # QGIS layer & feature for the single-trace cursor
        # Initialize to the pole, then expect the viewer to update it
        # immediately.
        trace_geometry = QgsPoint(0, -90)
        trace_symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": QtGui.QColor.fromRgb(255, 255, 0, 255),
                "size": "10",
                "size_unit": "Point",
            }
        )
        trace_feature = QgsFeature()
        trace_feature.setGeometry(trace_geometry)
        trace_uri = "point?crs=epsg:4326"
        trace_layer = QgsVectorLayer(trace_uri, "Highlighted Trace", "memory")
        trace_provider = trace_layer.dataProvider()
        trace_provider.addFeature(trace_feature)
        trace_layer.renderer().setSymbol(trace_symbol)
        trace_layer.updateExtents()
        QgsProject.instance().addMapLayer(trace_layer, False)
        transect_group.addLayer(trace_layer)

        # Features for the displayed segment.
        # For my example, I just used all of them. Will probably need to downsample!
        selected_geometry = QgsLineString([QgsPoint(0, -90)])
        selected_feature = QgsFeature()
        selected_feature.setGeometry(selected_geometry)

        selected_uri = "LineString?crs=epsg:4326"
        selected_layer = QgsVectorLayer(selected_uri, "Selected Region", "memory")

        selected_symbol = QgsLineSymbol.createSimple(
            {
                "color": QtGui.QColor.fromRgb(255, 128, 30, 255),
                "line_width": 2,
                "line_width_units": "Point",
            }
        )
        selected_layer.renderer().setSymbol(selected_symbol)

        selected_provider = selected_layer.dataProvider()
        selected_provider.addFeature(selected_feature)
        selected_layer.updateExtents()

        QgsProject.instance().addMapLayer(selected_layer, False)
        transect_group.addLayer(selected_layer)

        # Finally, feature for the entire transect
        # TODO: How to get the geometry _here_? We should know it
        # at this point, and it won't change. However, all other
        # geometry is provided in one of the callbacks...
        segment_geometry = QgsLineString([QgsPoint(0, -90)])

        segment_feature = QgsFeature()
        segment_feature.setGeometry(segment_geometry)

        segment_uri = "LineString?crs=epsg:4326"
        segment_layer = QgsVectorLayer(segment_uri, "Full Transect", "memory")

        segment_symbol = QgsLineSymbol.createSimple(
            {
                "color": QtGui.QColor.fromRgb(255, 0, 0, 255),
                "line_width": 1,
                "line_width_units": "Point",
            }
        )
        segment_layer.renderer().setSymbol(segment_symbol)
        segment_provider = segment_layer.dataProvider()
        segment_provider.addFeature(segment_feature)

        segment_layer.updateExtents()

        QgsProject.instance().addMapLayer(segment_layer, False)
        transect_group.addLayer(segment_layer)

        self.transect_groups[transect_name] = transect_group
        self.trace_features[transect_name] = trace_feature
        self.trace_layers[transect_name] = trace_layer
        self.radar_xlim_features[transect_name] = selected_feature
        self.radar_xlim_layers[transect_name] = selected_layer
        self.segment_features[transect_name] = segment_feature
        self.segment_layers[transect_name] = segment_layer

    def update_trace_callback(self, transect_name, lon, lat):
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

    def update_radar_xlim_callback(self, transect_name, points):
        QgsMessageLog.logMessage(f"update_selected_callback with {len(points)} points!")
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
        QgsMessageLog.logMessage(f"update_segment_points with {len(points)} points!")
        segment_geometry = QgsGeometry(
            QgsLineString([QgsPoint(lon, lat) for lon, lat in points])
        )
        segment_layer = self.segment_layers[transect_name]
        segment_layer.startEditing()
        segment_feature = self.segment_features[transect_name]
        segment_layer.changeGeometry(segment_feature.id(), segment_geometry)
        segment_layer.commitChanges()

    def selected_download_point_callback(self, point: QgsPoint):
        op = QIceRadarPlugin.Operation.DOWNLOAD
        self.selected_point_callback(op, point)

    def selected_viewer_point_callback(self, point: QgsPoint):
        op = QIceRadarPlugin.Operation.VIEW
        self.selected_point_callback(op, point)

    # TODO: This works, but only for one radargram. If we want to support more, should probably keep a list of dock widgets!
    def selected_point_callback(self, operation: Operation, point: QgsPointXY) -> None:
        QgsMessageLog.logMessage(f"Got point! {point.x()}, {point.y()}")

        # TODO: Really, if it is None, this should be an error condition.
        if self.prev_map_tool is not None:
            self.iface.mapCanvas().setMapTool(self.prev_map_tool)
            # self.prev_map_tool = None

        if self.spatial_index is None:
            errmsg = "Spatial index not created -- bug!!"
            QgsMessageLog.logMessage(errmsg)
            return

        neighbors = self.spatial_index.nearestNeighbor(point, 5)
        neighbor_names = []
        QgsMessageLog.logMessage("Got neighbors!")
        root = QgsProject.instance().layerTreeRoot()
        print(f"Tried to get project root! {root}")
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

        selection_widget = QIceRadarSelectionWidget(
            self.iface,
            neighbor_names
        )
        selection_widget.selected_radargram.connect(
            lambda transect, op=operation: self.selected_transect_callback(op, transect)
        )
        # Chosen transect is set via callback, rather than direct return value
        selection_widget.run()

    def ensure_valid_configuration(self) -> bool:
        # First, make sure we at least have the root data directory configured
        if not config_is_valid(self.config):
            cw = QIceRadarConfigWidget(self.iface, self.config, self.set_config)
            # Config is set via callback, rather than direct return value
            cw.run()

        if not config_is_valid(self.config):
            QgsMessageLog.logMessage("Invalid configuration; can't start QIceRadar")
            return False
        else:
            QgsMessageLog.logMessage(f"Config = {self.config}; ready for use!")
            return True

    def handle_configure_signal(self) -> None:
        cw = QIceRadarConfigWidget(self.iface, self.config, self.set_config)
        # Config is set via callback, rather than direct return value
        cw.run()

    def update_download_renderer(self):
        """
        We indicate which data has been downloaded by changing the
        renderer to be rule-based, checking whether the file exists.
        """
        # This is copied from building the spatial index
        QgsMessageLog.logMessage("Trying to modify layer renderers")
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
        else:
            QgsMessageLog.logMessage("Found QIceRadar group!")

        # Iterate through all layers in the group
        for ll in qiceradar_group.findLayers():
            # get the QgsMapLayer from the QgsLayerTreeLayer
            layer = ll.layer()
            features = layer.getFeatures()
            f0 = next(features)
            # Only need to check availability of single features, since all in
            # the layer will be the same.
            if f0.attributeMap()['availability'] in ['u', 'a']:
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
            region = f0.attributeMap()['region'].upper()
            institution = f0.attributeMap()['institution']
            campaign = f0.attributeMap()['campaign']
            # TODO: This may not work on windows ...
            dl_rule.setFilterExpression(f"""file_exists('{self.config.rootdir}/' + "relative_path")""")
            dl_rule.symbol().setColor(QtGui.QColor(133, 54, 229, 255))
            root_rule.appendChild(dl_rule)

            else_rule = root_rule.children()[0].clone()
            else_rule.setLabel("Available")
            else_rule.setFilterExpression('ELSE')
            else_rule.symbol().setColor(QtGui.QColor(31, 120, 180, 255))
            root_rule.appendChild(else_rule)

            root_rule.removeChildAt(0)

            layer.setRenderer(renderer)
            layer.triggerRepaint()  # This causes it to apply + redraw
            ll.setExpanded(False)

        self.download_renderer_added = True

    def run_downloader(self) -> None:
        QgsMessageLog.logMessage("run downloader")
        if not self.ensure_valid_configuration():
            return
        if self.spatial_index is None:
            self.build_spatial_index()
        if not self.download_renderer_added:
            self.update_download_renderer()
        # Don't want to bop back to other qiceradar tool after use;
        # should go back to e.g. zoom tool
        curr_tool = self.iface.mapCanvas().mapTool()
        if not isinstance(curr_tool, QIceRadarSelectionTool):
            self.prev_map_tool = curr_tool
        if self.prev_map_tool is None:
            # mypy doesn't like this; not sure why QgsMapToolPan isn't accepted as a QgsMapTool, which is its base class
            self.prev_map_tool = QgsMapToolPan
        # TODO: this lambda is the only place run_download differs from run_viewer
        # Should I re-combine them with another "operation" parameter?
        download_selection_tool = QIceRadarSelectionTool(self.iface.mapCanvas())
        download_selection_tool.selected_point.connect(self.selected_download_point_callback)
        try:
            download_selection_tool.deactivated.connect(
                lambda ch=False: self.downloader_action.setChecked(ch)
            )
            download_selection_tool.activated.connect(
                lambda ch=True: self.downloader_action.setChecked(ch)
            )
        except AttributeError:
            # TODO: Figure out why sometimes these actions don't exist at startup
            pass
        self.iface.mapCanvas().setMapTool(download_selection_tool)

    def run_viewer(self) -> None:
        # The QIceRadar tool is a series of widgets, kicked off by clicking on the icon.
        QgsMessageLog.logMessage("run viewer")

        self.create_radar_viewer_group()

        if not self.ensure_valid_configuration():
            return

        # Next, make sure the spatial index has been initialized
        # TODO: detect when project changes and re-initialize!
        if self.spatial_index is None:
            self.build_spatial_index()

        if not self.download_renderer_added:
            self.update_download_renderer()

        # Create a MapTool to select point on map. After this point, it is callback driven.
        # TODO: This feels like something that should be handled in the SelectionTool,
        #  not in the plugin
        # mypy doesn't like this: "expression has type "type[QgsMapToolPan]", variable has type "QgsMapTool | None")"
        self.prev_map_tool = self.iface.mapCanvas().mapTool()
        if self.prev_map_tool is None:
            # mypy doesn't like this; not sure why QgsMapToolPan isn't accepted as a QgsMapTool, which is its base class
            self.prev_map_tool = QgsMapToolPan
        viewer_selection_tool = QIceRadarSelectionTool(self.iface.mapCanvas())
        viewer_selection_tool.selected_point.connect(self.selected_viewer_point_callback)
        viewer_selection_tool.deactivated.connect(
            lambda ch=False: self.viewer_action.setChecked(ch)
        )
        viewer_selection_tool.activated.connect(
            lambda ch=True: self.viewer_action.setChecked(ch)
        )
        self.iface.mapCanvas().setMapTool(viewer_selection_tool)

    def start_download(
        self, granule: str, url: str, destination_filepath, filesize: int
    ):
        """
        After the confirmation dialog has finished, this section
        actually kicks off the download
        """
        # TODO: remove below mkdir after making sure it's in the other widgets
        # self.granule_filepath.parents[0].mkdir(parents=True, exist_ok=True)
        QgsMessageLog.logMessage("TODO: Actually download radargram!")
        # Oooooh. drat. the confirmation dialogue can't own the widget.abs
        # So, I need to figure out how to have this emit a signal that the
        # main plugin handles.
        if self.download_window is None:
            self.download_window = DownloadWindow(self.iface)
            self.download_window.download_finished.connect(self.update_download_renderer)
            self.dock_widget = QtWidgets.QDockWidget("QIceRadar Downloader")
            self.dock_widget.setWidget(self.download_window)
            # TODO: Figure out how to handle the user closing the dock widget
            self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.dock_widget)
        # TODO: add downloadTransectWidget to the download window!
        self.download_window.download(granule, url, destination_filepath, filesize)
