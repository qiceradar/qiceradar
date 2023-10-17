import PyQt5.QtWidgets as QtWidgets

from qgis.core import QgsMessageLog


class RadarViewerRadargramWidget(QtWidgets.QWidget):
    def __init__(self):
        super(RadarViewerRadargramWidget, self).__init__()
        self.setup_ui()

    def setup_ui(self):
        self.main_hbox = QtWidgets.QHBoxLayout()
        self.temp_label = QtWidgets.QLabel("NYI: Radargram Viewer")
        self.main_hbox.addWidget(self.temp_label)
        self.setLayout(self.main_hbox)

    def run(self):
        QgsMessageLog.logMessage("RadarViewerRadargramWidget.run()")
        self.show()
