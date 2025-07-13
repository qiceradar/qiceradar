# Copyright 2025 Laura Lindzey, UW-APL
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
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

import time

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
import PyQt5.QtXml as QtXml
from qgis.core import (
    Qgis,
    QgsLayerTree,
    QgsLayerTreeModel,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsMessageLog,
    QgsRuleBasedRenderer,
    QgsVectorLayer,
)

try:
    # Needed pre-3.30
    from qgis.core import QgsUnitTypes
except Exception:
    pass
from qgis.gui import (
    QgsLayerTreeView,
    QgsLayerTreeViewMenuProvider,
)


class SymbologyMenuProvider(QgsLayerTreeViewMenuProvider):
    """
    For the symbology widget, the user needs to be able to edit the layer
    symbols. I did not find a straightforward way to pop up only the edit
    symbol dialogue, so this pops up the entire layer properties dialog.
    """

    def __init__(self, view, iface):
        super().__init__()
        self.view = view
        self.iface = iface

    def createContextMenu(self):
        if not self.view.currentLayer():
            return None

        menu = QtWidgets.QMenu()
        layer_properties_action = QtWidgets.QAction("Layer Properties", menu)
        layer_properties_action.triggered.connect(self.open_layer_properties)
        menu.addAction(layer_properties_action)
        return menu

    def open_layer_properties(self):
        self.iface.showLayerProperties(self.view.currentLayer(), "mOptsPage_Symbology")


class SymbologyWidget(QtWidgets.QWidget):
    """
    Create layer tree containing dummy layers for each of the symbols
    the user might want to style.

    Attach callbacks to these dummy layers that then emit a signal indicating
    that the corresponding layer styles should be updated.
    """

    trace_style_changed = QtCore.pyqtSignal(str)
    selected_style_changed = QtCore.pyqtSignal(str)
    segment_style_changed = QtCore.pyqtSignal(str)
    unavailable_point_style_changed = QtCore.pyqtSignal(str)
    unavailable_line_style_changed = QtCore.pyqtSignal(str)
    categorized_style_changed = QtCore.pyqtSignal(str)

    # Keys for accessing layer styles in the global QGIS settings
    trace_style_config_key = "qiceradar_config/trace_layer_style"
    selected_style_config_key = "qiceradar_config/selected_layer_style"
    segment_style_config_key = "qiceradar_config/segment_layer_style"
    unavailable_point_style_config_key = (
        "qiceradar_config/unavailable_point_layer_style"
    )
    unavailable_line_style_config_key = "qiceradar_config/unavailable_line_layer_style"
    categorized_style_config_key = "qiceradar_config/categorized_layer_style"

    def __init__(self, iface) -> None:
        super().__init__()
        self.iface = iface
        # I have not been able to find a signal that triggers only once
        # when the user changes the style of a layer, so we detect multiple
        # calls and only update on the first.
        self.style_changed_time = 0.0

        self.tree_root, self.view, self.model = SymbologyWidget.setup_tree_view(
            self.iface
        )
        self.setup_layers(self.tree_root)
        self.setup_ui()

    def setup_ui(self) -> None:
        label = QtWidgets.QLabel("Layer Styles")
        label.setAlignment(QtCore.Qt.AlignCenter)
        reset_button = QtWidgets.QPushButton("Reset Defaults")
        reset_button.clicked.connect(self.reset_styles_to_default)

        vbox = QtWidgets.QVBoxLayout()
        vbox.addWidget(label)
        vbox.addWidget(self.view)
        vbox.addWidget(reset_button)
        self.setLayout(vbox)

    @staticmethod
    def setup_tree_view(iface) -> (QgsLayerTree, QgsLayerTreeView, QgsLayerTreeModel):
        root = QgsLayerTree()
        view = QgsLayerTreeView()
        model = QgsLayerTreeModel(root)
        model.setFlag(QgsLayerTreeModel.AllowNodeChangeVisibility, False)
        model.setFlag(QgsLayerTreeModel.AllowNodeRename, False)
        model.setFlag(QgsLayerTreeModel.AllowNodeReorder, False)
        view.setModel(model)
        view.setMenuProvider(SymbologyMenuProvider(view, iface))
        return root, view, model

    def setup_layers(self, root: QgsLayerTree) -> None:
        """
        Create layers that will be used for controlling the symbology
        of the layers managed by QIceRadar
        """
        self.trace_layer = SymbologyWidget.add_trace_layer(root)
        self.selected_layer = SymbologyWidget.add_selected_layer(root)
        self.segment_layer = SymbologyWidget.add_segment_layer(root)
        self.point_layer = SymbologyWidget.add_unavailable_multipoint_layer(root)
        self.line_layer = SymbologyWidget.add_unavailable_linestring_layer(root)
        self.categorized_layer = SymbologyWidget.add_categorized_layer(root)

        # The styleChanged signal is emitted twice when the user clicks
        # "Apply" or "OK" in the layer properties dialog; I experimented
        # with other signals to no avail:
        # * styleLoaded is never triggered
        # * rendererChanged and styleChanged trigger twice
        # * repaintRequester triggers 3x
        # So ... I have implemented logic to only update styles once per second
        self.trace_layer.styleChanged.connect(self.update_trace_layer_style)
        self.selected_layer.styleChanged.connect(self.update_selected_layer_style)
        self.segment_layer.styleChanged.connect(self.update_segment_layer_style)
        self.point_layer.styleChanged.connect(self.update_unavailable_point_layer_style)
        self.line_layer.styleChanged.connect(self.update_unavailable_line_layer_style)
        self.categorized_layer.styleChanged.connect(self.update_categorized_layer_style)

    def reset_styles_to_default(self) -> None:
        """
        Reset all styles in the symbology widget to their defaults
        """
        trace_symbol = SymbologyWidget.make_trace_symbol()
        self.trace_layer.renderer().setSymbol(trace_symbol)

        selected_symbol = SymbologyWidget.make_selected_symbol()
        self.selected_layer.renderer().setSymbol(selected_symbol)

        segment_symbol = SymbologyWidget.make_segment_symbol()
        self.segment_layer.renderer().setSymbol(segment_symbol)

        multipoint_symbol = SymbologyWidget.make_unavailable_point_symbol()
        self.point_layer.renderer().setSymbol(multipoint_symbol)

        linestring_symbol = SymbologyWidget.make_unavailable_line_symbol()
        self.line_layer.renderer().setSymbol(linestring_symbol)

        categorized_renderer = SymbologyWidget.make_categorized_renderer()
        self.categorized_layer.setRenderer(categorized_renderer)

        for layer in [
            self.trace_layer,
            self.selected_layer,
            self.segment_layer,
            self.point_layer,
            self.line_layer,
            self.categorized_layer,
        ]:
            self.view.refreshLayerSymbology(layer.id())

        # Every style might have changed, so go ahead and trigger updates for all.
        # We need to force the update since this programmatic triggering
        # may trigger them faster than the timeout to detect duplicate signals.
        self.update_trace_layer_style(force_update=True)
        self.update_selected_layer_style(force_update=True)
        self.update_segment_layer_style(force_update=True)
        self.update_unavailable_point_layer_style(force_update=True)
        self.update_unavailable_line_layer_style(force_update=True)
        # We don't need to manually force the update for the categorized layer,
        # since setting the renderer triggers that.
        # self.update_categorized_layer_style(force_update=True)

    @staticmethod
    def make_trace_symbol() -> QgsMarkerSymbol:
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": QtGui.QColor.fromRgb(255, 255, 0, 255),
            "size": "8",
            "outline_style": "no",
        })
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Points)
        except Exception:
            # Prior to QGIS 3.30, these enums were organized differently
            symbol.setOutputUnit(QgsUnitTypes.RenderPoints)
        return symbol

    @staticmethod
    def add_trace_layer(root: QgsLayerTree) -> QgsVectorLayer:
        trace_uri = "point?crs=epsg:4326"
        trace_layer = QgsVectorLayer(trace_uri, "Highlighted Trace", "memory")

        qs = QtCore.QSettings()
        style_str = qs.value(SymbologyWidget.trace_style_config_key, None)
        if style_str is None:
            trace_symbol = SymbologyWidget.make_trace_symbol()
            trace_layer.renderer().setSymbol(trace_symbol)
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            trace_layer.importNamedStyle(doc)

        root.addLayer(trace_layer)
        return trace_layer

    @staticmethod
    def make_selected_symbol() -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple({
            "color": QtGui.QColor.fromRgb(255, 128, 30, 255),
            "line_width": 2,
        })
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Points)
        except Exception:
            # Prior to QGIS 3.30, these enums were organized differently
            symbol.setOutputUnit(QgsUnitTypes.RenderPoints)
        return symbol

    @staticmethod
    def add_selected_layer(root: QgsLayerTree) -> QgsVectorLayer:
        selected_uri = "LineString?crs=epsg:4326"
        selected_layer = QgsVectorLayer(selected_uri, "Selected Region", "memory")

        qs = QtCore.QSettings()
        style_str = qs.value(SymbologyWidget.selected_style_config_key, None)
        if style_str is None:
            selected_symbol = SymbologyWidget.make_selected_symbol()
            selected_layer.renderer().setSymbol(selected_symbol)
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            selected_layer.importNamedStyle(doc)

        root.addLayer(selected_layer)
        return selected_layer

    @staticmethod
    def make_segment_symbol() -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple({
            "color": QtGui.QColor.fromRgb(255, 0, 0, 255),
            "line_width": 1,
        })
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Points)
        except Exception:
            # Prior to QGIS 3.30, these enums were organized differently
            symbol.setOutputUnit(QgsUnitTypes.RenderPoints)
        return symbol

    @staticmethod
    def add_segment_layer(root: QgsLayerTree) -> QgsVectorLayer:
        segment_uri = "LineString?crs=epsg:4326"
        segment_layer = QgsVectorLayer(segment_uri, "Full Transect", "memory")

        qs = QtCore.QSettings()
        style_str = qs.value(SymbologyWidget.segment_style_config_key, None)
        if style_str is None:
            segment_symbol = SymbologyWidget.make_segment_symbol()
            segment_layer.renderer().setSymbol(segment_symbol)
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            segment_layer.importNamedStyle(doc)

        root.addLayer(segment_layer)
        return segment_layer

    @staticmethod
    def make_unavailable_point_symbol() -> QgsMarkerSymbol:
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": QtGui.QColor.fromRgb(251, 154, 153, 255),
            "size": "1",
            "outline_style": "no",
        })
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Points)
        except Exception:
            # Prior to QGIS 3.30, these enums were organized differently
            symbol.setOutputUnit(QgsUnitTypes.RenderPoints)
        return symbol

    @staticmethod
    def add_unavailable_multipoint_layer(root: QgsLayerTree) -> QgsVectorLayer:
        multipoint_uri = "point?crs=epsg:4326"
        multipoint_layer = QgsVectorLayer(
            multipoint_uri, "Unavailable (Points)", "memory"
        )

        qs = QtCore.QSettings()
        style_str = qs.value(SymbologyWidget.unavailable_point_style_config_key, None)
        if style_str is None:
            multipoint_symbol = SymbologyWidget.make_unavailable_point_symbol()
            multipoint_layer.renderer().setSymbol(multipoint_symbol)
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            multipoint_layer.importNamedStyle(doc)

        root.addLayer(multipoint_layer)
        return multipoint_layer

    @staticmethod
    def make_unavailable_line_symbol() -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple({
            "color": QtGui.QColor.fromRgb(251, 154, 153, 255),
            "line_width": 1,
        })
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Points)
        except Exception:
            # Prior to QGIS 3.30, these enums were organized differently
            symbol.setOutputUnit(QgsUnitTypes.RenderPoints)
        return symbol

    @staticmethod
    def add_unavailable_linestring_layer(root: QgsLayerTree) -> QgsVectorLayer:
        linestring_uri = "LineString?crs=epsg:4326"
        linestring_layer = QgsVectorLayer(
            linestring_uri, "Unavailable (Lines)", "memory"
        )

        qs = QtCore.QSettings()
        style_str = qs.value(SymbologyWidget.unavailable_line_style_config_key, None)
        if style_str is None:
            linestring_symbol = SymbologyWidget.make_unavailable_line_symbol()
            linestring_layer.renderer().setSymbol(linestring_symbol)
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            linestring_layer.importNamedStyle(doc)

        root.addLayer(linestring_layer)
        return linestring_layer

    @staticmethod
    def make_categorized_renderer() -> QgsRuleBasedRenderer:
        """
        This sets the style for named rules, but is not able to define the
        filter expressions since they depend on the root directory, which
        isn't known until the project loads and we search for the index group
        """
        symbol = QgsLineSymbol()
        renderer = QgsRuleBasedRenderer(symbol)
        root_rule = renderer.rootRule()

        dl_rule = root_rule.children()[0].clone()
        dl_rule.setLabel("Downloaded")
        dl_rule.symbol().setWidth(0.35)  # Make them more visible
        dl_rule.symbol().setColor(QtGui.QColor(133, 54, 229, 255))
        root_rule.appendChild(dl_rule)

        supported_rule = root_rule.children()[0].clone()
        supported_rule.setLabel("Supported")
        supported_rule.symbol().setColor(QtGui.QColor(31, 120, 180, 255))
        root_rule.appendChild(supported_rule)

        else_rule = root_rule.children()[0].clone()
        else_rule.setLabel("Available")
        else_rule.symbol().setColor(QtGui.QColor(68, 68, 68, 255))
        root_rule.appendChild(else_rule)

        root_rule.removeChildAt(0)
        return renderer

    @staticmethod
    def add_categorized_layer(root: QgsLayerTree) -> QgsVectorLayer:
        categorized_uri = "LineString?crs=epsg:4326"
        categorized_layer = QgsVectorLayer(
            categorized_uri, "Radargram Availability", "memory"
        )

        qs = QtCore.QSettings()
        style_str = qs.value(SymbologyWidget.categorized_style_config_key, None)
        if style_str is None:
            renderer = SymbologyWidget.make_categorized_renderer()
            categorized_layer.setRenderer(renderer)
        else:
            doc = QtXml.QDomDocument()
            doc.setContent(style_str)
            categorized_layer.importNamedStyle(doc)

        root.addLayer(categorized_layer)
        return categorized_layer

    def deduplicate_updates(fun):
        def wrapper(self, *args, **kwargs):
            try:
                force_update = kwargs["force_update"]
            except Exception:
                force_update = False

            dt = time.time() - self.style_changed_time
            if dt < 1.0 and not force_update:
                QgsMessageLog.logMessage("...repeated call, skipping (decorator!)")
                return
            fun(self, *args, **kwargs)
            self.style_changed_time = time.time()

        return wrapper

    @deduplicate_updates
    def update_trace_layer_style(self, force_update=False):
        QgsMessageLog.logMessage("update_trace_layer_style")
        doc = QtXml.QDomDocument()
        self.trace_layer.exportNamedStyle(doc)
        style_str = doc.toString()
        qs = QtCore.QSettings()
        qs.setValue(self.trace_style_config_key, style_str)
        self.trace_style_changed.emit(style_str)

    @deduplicate_updates
    def update_selected_layer_style(self, force_update=False):
        QgsMessageLog.logMessage("update_selected_layer_style")
        doc = QtXml.QDomDocument()
        self.selected_layer.exportNamedStyle(doc)
        style_str = doc.toString()
        qs = QtCore.QSettings()
        qs.setValue(self.selected_style_config_key, style_str)
        self.selected_style_changed.emit(style_str)

    @deduplicate_updates
    def update_segment_layer_style(self, force_update=False):
        QgsMessageLog.logMessage("update_segment_layer_style")
        doc = QtXml.QDomDocument()
        self.segment_layer.exportNamedStyle(doc)
        style_str = doc.toString()
        qs = QtCore.QSettings()
        qs.setValue(self.segment_style_config_key, style_str)
        self.segment_style_changed.emit(style_str)

    @deduplicate_updates
    def update_unavailable_point_layer_style(self, force_update=False):
        QgsMessageLog.logMessage("update_unavailable_point_layer_style")
        doc = QtXml.QDomDocument()
        self.point_layer.exportNamedStyle(doc)
        style_str = doc.toString()
        qs = QtCore.QSettings()
        qs.setValue(self.unavailable_point_style_config_key, style_str)
        self.unavailable_point_style_changed.emit(style_str)

    @deduplicate_updates
    def update_unavailable_line_layer_style(self, force_update=False):
        QgsMessageLog.logMessage("update_unavailable_line_layer_style")
        doc = QtXml.QDomDocument()
        self.line_layer.exportNamedStyle(doc)
        style_str = doc.toString()
        qs = QtCore.QSettings()
        qs.setValue(self.unavailable_line_style_config_key, style_str)
        self.unavailable_line_style_changed.emit(style_str)

    @deduplicate_updates
    def update_categorized_layer_style(self, force_update=False):
        QgsMessageLog.logMessage("update_categorized_layer_style")
        doc = QtXml.QDomDocument()
        self.categorized_layer.exportNamedStyle(doc)
        style_str = doc.toString()
        qs = QtCore.QSettings()
        qs.setValue(self.categorized_style_config_key, style_str)
        self.categorized_style_changed.emit(style_str)
