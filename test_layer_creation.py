"""
Experimenting with manually creating the layer and highlighted areas as a
mockup for the future radar viewer interface.
"""
# NB: you can set fields on a layer. Maybe this is the way to add metadata?




# Load data
import netCDF4 as nc
import pathlib
granule = "/Users/lindzey/RadarData/ANTARCTIC/UTIG/AGASEA/X63a/X63a_3.nc"
segment_name = pathlib.Path(granule).stem
data = nc.Dataset(granule, 'r')
latitude = data['latitude'][:].data
longitude = data['longitude'][:].data

# Create layer group
root = QgsProject.instance().layerTreeRoot()
viewer_group = root.insertGroup(0, "Radar Viewer")
segment_group = viewer_group.insertGroup(0, segment_name)

# Add symbol for the currently-selected trace
trace_idx = 1330
trace_geometry = QgsPoint(longitude[trace_idx], latitude[trace_idx])
trace_symbol = QgsMarkerSymbol.createSimple({'name': 'circle',
                                             'color': QColor.fromRgb(255, 255, 0, 255),
                                             'size': '10',
                                             'size_unit': 'Point',
                                           })

trace_feature = QgsFeature()
trace_feature.setGeometry(trace_geometry)
uri = "point?crs=epsg:4326"
trace_layer = QgsVectorLayer(uri, "Trace", "memory")
trace_provider = trace_layer.dataProvider()
trace_provider.addFeature(trace_feature)
trace_layer.renderer().setSymbol(trace_symbol)
trace_layer.updateExtents()
QgsProject.instance().addMapLayer(trace_layer, False)
segment_group.addLayer(trace_layer)

# Add symbol for the first trace
first_trace_geometry = QgsPoint(longitude[0], latitude[0])
first_trace_symbol = QgsMarkerSymbol.createSimple({'name': 'circle',
                                             'color': QColor.fromRgb(255, 0, 0, 255),
                                             'size': '5',
                                             'size_unit': 'Point',
                                           })

first_trace_feature = QgsFeature()
first_trace_feature.setGeometry(first_trace_geometry)
uri = "point?crs=epsg:4326"
first_trace_layer = QgsVectorLayer(uri, "First Trace", "memory")
first_trace_provider = first_trace_layer.dataProvider()
first_trace_provider.addFeature(first_trace_feature)
first_trace_layer.renderer().setSymbol(first_trace_symbol)
first_trace_layer.updateExtents()
QgsProject.instance().addMapLayer(first_trace_layer, False)
segment_group.addLayer(first_trace_layer)


######## Plot only the selected region
start_trace = 830
end_trace = 1830
selected_geometry = QgsLineString([QgsPoint(longitude[idx], latitude[idx])
                                   for idx in range(start_trace, end_trace)])

selected_feature = QgsFeature()
selected_feature.setGeometry(selected_geometry)

uri = "LineString?crs=epsg:4326"
selected_layer = QgsVectorLayer(uri, "Region", "memory")

selected_symbol = QgsLineSymbol.createSimple({'color': QColor.fromRgb(255, 128, 30, 255),
                                             'line_width': 2,
                                             'line_width_units': 'Point',
                                           })

selected_layer.renderer().setSymbol(selected_symbol)


selected_provider = selected_layer.dataProvider()
selected_provider.addFeature(selected_feature)
selected_layer.updateExtents()

QgsProject.instance().addMapLayer(selected_layer, False)
segment_group.addLayer(selected_layer)



######## Plot the length of the entire granule

segment_geometry = QgsLineString([QgsPoint(lon, lat) 
                                 for lon, lat in zip(longitude, latitude)])

segment_feature = QgsFeature()
segment_feature.setGeometry(segment_geometry)

uri = "LineString?crs=epsg:4326"
segment_layer = QgsVectorLayer(uri, "Segment", "memory")

segment_symbol = QgsLineSymbol.createSimple({'color': QColor.fromRgb(255, 0, 0, 255),
                                             'line_width': 1,
                                             'line_width_units': 'Point',
                                           })

segment_layer.renderer().setSymbol(segment_symbol)


segment_provider = segment_layer.dataProvider()
segment_provider.addFeature(segment_feature)
# TODO: Style this segment.

segment_layer.updateExtents()

QgsProject.instance().addMapLayer(segment_layer, False)
segment_group.addLayer(segment_layer)

# OH. There's also a setRenderer -- that may be what I need for the KML layers.