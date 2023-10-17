import PyQt5.QtWidgets as QtWidgets

from qgis.core import QgsMessageLog


class RadarViewerRadargramWidget(QtWidgets.QMainWindow):
    def __init__(self):
        super(RadarViewerRadargramWidget, self).__init__()
        self.setup_ui()

    def setup_ui(self):
        self.main_hbox = QtWidgets.QHBoxLayout()
        self.temp_label = QtWidgets.QLabel("NYI: Radargram Viewer")
        self.main_hbox.addWidget(self.temp_label)
        self.setLayout(self.main_hbox)
        # TODO: I'm not sure that I should be using a QMainWindow anyways;
        #   if I stick with that,
        self.setCentralWidget(self.temp_label)
