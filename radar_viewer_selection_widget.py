from typing import Callable, List

import PyQt5.QtWidgets as QtWidgets
import qgis.core
import qgis.gui
from qgis.core import QgsMessageLog
from qgis.gui import QgsMapTool


class RadarViewerSelectionTool(QgsMapTool):
    """
    When activated, allows user to click on map to select closest transects.
    """

    def __init__(self, canvas, point_callback):
        super(RadarViewerSelectionTool, self).__init__(canvas)
        # self.canvas = canvas
        self.point_callback = point_callback

    def canvasReleaseEvent(self, event):
        QgsMessageLog.logMessage("canvas release event!")
        pt = event.mapPoint()
        self.point_callback(pt)
        self.deactivate()  # A new tool will be created the next time the icon is clicked


class RadarViewerSelectionWidget(QtWidgets.QDialog):
    """
    Display closest N transects to clicked point, prompt user to specify which they want.

    Simply going with the closest will not work, since there are often re-flights
    of the same line, impossible to distinguish with a click in map view.
    """

    def __init__(
        self, iface, transects: List[str], transect_callback: Callable[[str], None]
    ):
        super(RadarViewerSelectionWidget, self).__init__()
        self.iface = iface
        self.transects = transects
        self.transect_callback = transect_callback
        self.setup_ui()

    def ok_pushbutton_clicked(self, _event):
        for rb in self.transect_radiobuttons:
            if rb.isChecked():
                self.transect_callback(rb.text())
                self.close()

    def setup_ui(self):
        self.radio_vbox = QtWidgets.QVBoxLayout()
        self.transect_radiobuttons = []
        for transect in self.transects:
            rb = QtWidgets.QRadioButton(transect)
            self.transect_radiobuttons.append(rb)
            self.radio_vbox.addWidget(rb)

        self.control_hbox = QtWidgets.QHBoxLayout()
        self.cancel_pushbutton = QtWidgets.QPushButton("Cancel")
        self.cancel_pushbutton.clicked.connect(self.close)
        self.control_hbox.addWidget(self.cancel_pushbutton)
        self.control_hbox.addStretch(1)
        self.ok_pushbutton = QtWidgets.QPushButton("OK")
        self.ok_pushbutton.clicked.connect(self.ok_pushbutton_clicked)
        self.control_hbox.addWidget(self.ok_pushbutton)

        self.vbox = QtWidgets.QVBoxLayout()
        self.vbox.addLayout(self.radio_vbox)
        self.vbox.addLayout(self.control_hbox)
        self.setLayout(self.vbox)
        self.setWindowTitle("Select Transect")

    def run(self):
        QgsMessageLog.logMessage("RadarViewerSelectionWidget.run()")
        # NB: using `exec` creates a modal dialogue, that the user must
        #     deal with before continuing to interact with QGIS
        self.exec()
