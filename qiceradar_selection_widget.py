from typing import List

import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets
from qgis.core import QgsMessageLog, QgsPointXY
from qgis.gui import QgisInterface, QgsMapCanvas, QgsMapMouseEvent, QgsMapTool


class QIceRadarSelectionTool(QgsMapTool):
    """
    When activated, allows user to click on map to select closest transects.

    This is totally generic between download and visualizer, since
    it simply emits a signal with a QgsPointXY.

    A new tool will be created for each time a qiceradar tooltip
    icon is clicked.
    """

    selected_point = QtCore.pyqtSignal(QgsPointXY)

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super(QIceRadarSelectionTool, self).__init__(canvas)

    def canvasReleaseEvent(self, event: QgsMapMouseEvent) -> None:
        QgsMessageLog.logMessage("canvas release event!")
        pt = event.mapPoint()
        self.selected_point.emit(pt)
        self.deactivate()


class QIceRadarSelectionWidget(QtWidgets.QDialog):
    """
    Display closest N transects to clicked point, prompt user to specify which they want.

    Simply going with the closest will not work, since there are often re-flights
    of the same line, impossible to distinguish with a click in map view.

    For now, both the download and the viewer code are sharing this
    widget; the list of transects to choose between is calculated elsewhere
    """

    selected_radargram = QtCore.pyqtSignal(str)

    def __init__(self, iface: QgisInterface, transects: List[str]) -> None:
        super(QIceRadarSelectionWidget, self).__init__()
        self.iface = iface
        self.transects = transects
        self.setup_ui()

    def ok_pushbutton_clicked(self, _checked: bool) -> None:
        for rb in self.transect_radiobuttons:
            if rb.isChecked():
                self.close()
                self.selected_radargram.emit(rb.text())

    def setup_ui(self) -> None:
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

    def run(self) -> None:
        QgsMessageLog.logMessage("QIceRadarSelectionWidget.run()")
        # NB: using `exec` creates a modal dialogue, that the user must
        #     deal with before continuing to interact with QGIS
        self.exec()
