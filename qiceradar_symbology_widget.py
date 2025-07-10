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

import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets

from qgis.core import (
    Qgis,
    QgsLayerTree,
    QgsLayerTreeModel,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsVectorLayer,
)
from qgis.gui import (
    QgsLayerTreeView,
    QgsLayerTreeViewMenuProvider,
)

class SymbologyMenuProvider(QgsLayerTreeViewMenuProvider):
    def __init__(self, view, iface):
        super().__init__()
        self.view = view
        self.iface = iface

    def createContextMenu(self):
        if not self.view.currentLayer():
            return None

        menu = QtWidgets.QMenu()
        layer_properties_action = QtWidgets.QAction("Layer Properties", menu)
        layer_properties_action.triggered.connect(self.openLayerProperties)
        menu.addAction(layer_properties_action)
        return menu

    def openLayerProperties(self):
        self.iface.showLayerProperties(self.view.currentLayer(), 'mOptsPage_Symbology')


class SymbologyWidget(QtWidgets.QWidget):
    def __init__(self, iface) -> None:
        super().__init__()
        self.iface = iface

        self.tree_root, self.view, self.model = SymbologyWidget.setup_tree_view(self.iface)
        self.setup_layers(self.tree_root)
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self.view)
        self.setLayout(layout)

    # TODO: need to disconnect callbacks when plugin is unloaded
    # TODO: hook these styles up to the configuration for save/load

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
        self.categorized_layer = SymbologyWidget.add_categorized_layer(root)
        self.multipoint_layer = SymbologyWidget.add_unavailable_multipoint_layer(root)
        self.linestring_layer = SymbologyWidget.add_unavailable_linestring_layer(root)

        # TODO: setup callbacks to act on the main layer tree root

    @staticmethod
    def add_unavailable_linestring_layer(root: QgsLayerTree) -> QgsVectorLayer:
        linestring_symbol = QgsLineSymbol.createSimple(
            {
                "color": QtGui.QColor.fromRgb(251, 154, 153, 255),
                "line_width": 1,
            }
        )
        # pre 3.30,  QgsUnitTypes.RenderPoints
        linestring_symbol.setOutputUnit(Qgis.RenderUnit.Points)
        linestring_uri = "LineString?crs=epsg:4326"
        linestring_layer = QgsVectorLayer(linestring_uri, "Unavailable (Lines)", "memory")
        linestring_layer.renderer().setSymbol(linestring_symbol)
        QgsProject.instance().addMapLayer(linestring_layer, False)
        root.addLayer(linestring_layer)
        return linestring_layer

    @staticmethod
    def add_unavailable_multipoint_layer(root: QgsLayerTree) -> QgsVectorLayer:
        multipoint_symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": QtGui.QColor.fromRgb(251, 154, 153, 255),
                "size": "1",
                "outline_style": "no"
            }
        )
        multipoint_symbol.setOutputUnit(Qgis.RenderUnit.Points)
        multipoint_uri = "point?crs=epsg:4326"
        multipoint_layer = QgsVectorLayer(multipoint_uri, "Unavailable (Points)", "memory")
        multipoint_layer.renderer().setSymbol(multipoint_symbol)
        QgsProject.instance().addMapLayer(multipoint_layer, False)
        root.addLayer(multipoint_layer)
        return multipoint_layer

    @staticmethod
    def add_categorized_layer(root: QgsLayerTree) -> QgsVectorLayer:
        categorized_uri = "LineString?crs=epsg:4326"
        categorized_layer = QgsVectorLayer(categorized_uri, "Radargram Availability", "memory")
        symbol = QgsSymbol.defaultSymbol(categorized_layer.geometryType())
        renderer = QgsRuleBasedRenderer(symbol)
        root_rule = renderer.rootRule()

        dl_rule = root_rule.children()[0].clone()
        dl_rule.setLabel("Downloaded")
        #QUESTION: Shall I go ahead and set the rules here, if we are going to be copying the symbology?
        # => NO. the rules are layer-dependent, since they encode the root directory
        dl_rule.symbol().setWidth(0.35) # Make them more visible
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

        categorized_layer.setRenderer(renderer)
        root.addLayer(categorized_layer)
        return categorized_layer

    @staticmethod
    def add_segment_layer(root: QgsLayerTree) -> QgsVectorLayer:
        segment_symbol = QgsLineSymbol.createSimple(
            {
                "color": QtGui.QColor.fromRgb(255, 0, 0, 255),
                "line_width": 1,
            }
        )
        segment_symbol.setOutputUnit(Qgis.RenderUnit.Points)
        segment_uri = "LineString?crs=epsg:4326"
        segment_layer = QgsVectorLayer(segment_uri, "Full Transect", "memory")
        segment_layer.renderer().setSymbol(segment_symbol)
        QgsProject.instance().addMapLayer(segment_layer, False)
        root.addLayer(segment_layer)
        return segment_layer

    @staticmethod
    def add_selected_layer(root: QgsLayerTree) -> QgsVectorLayer:
        selected_symbol = QgsLineSymbol.createSimple(
            {
                "color": QtGui.QColor.fromRgb(255, 128, 30, 255),
                "line_width": 2,
            }
        )
        selected_symbol.setOutputUnit(Qgis.RenderUnit.Points)
        selected_uri = "LineString?crs=epsg:4326"
        selected_layer = QgsVectorLayer(selected_uri, "Selected Region", "memory")
        selected_layer.renderer().setSymbol(selected_symbol)
        QgsProject.instance().addMapLayer(selected_layer, False)
        root.addLayer(selected_layer)
        return selected_layer

    @staticmethod
    def add_trace_layer(root: QgsLayerTree) -> QgsVectorLayer:
        trace_symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": QtGui.QColor.fromRgb(255, 255, 0, 255),
                "size": "8",
                "outline_style": "no"
            }
        )
        trace_symbol.setOutputUnit(Qgis.RenderUnit.Points)
        trace_uri = "point?crs=epsg:4326"
        trace_layer = QgsVectorLayer(trace_uri, "Highlighted Trace", "memory")
        trace_layer.renderer().setSymbol(trace_symbol)
        QgsProject.instance().addMapLayer(trace_layer, False)
        root.addLayer(trace_layer)
        return trace_layer
