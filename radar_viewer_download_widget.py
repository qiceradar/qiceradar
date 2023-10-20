import pathlib
from typing import Dict

import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets

from qgis.core import QgsMessageLog

from .radar_viewer_data_utils import get_granule_filepath


class RadarViewerDownloadWidget(QtWidgets.QDialog):
    def __init__(self, rootdir: pathlib.Path, attributes: Dict[str, str]):
        super(RadarViewerDownloadWidget, self).__init__()

        self.rootdir = rootdir
        self.attributes = attributes  # attributes from the feature
        self.setup_ui()

    def setup_ui(self):
        """
        UI should be something like:

        ------------ (campaign-specific widget)

        KOPRI-KRT1 data can be found at:
        Download the zip file and extract it to:
        Then try again.

        (only an OK button)

        ----


        -----
        # TODO/QUESTION: should downloader + viewer work at the segment or granule level?
        #    for now, I'm dealing with granules, but I kind of expect that it will be
        #    preferable to shove them all together.
        UTIG-??? data can be automatically downloaded.
        URI:

        The requested granule is _______ (MB/GB)
        """
        region = self.attributes["region"]
        institution = self.attributes["institution"]
        campaign = self.attributes["campaign"]
        segment = self.attributes["segment"]
        granule = self.attributes["granule"]
        granule_filepath = get_granule_filepath(
            self.rootdir, region, institution, campaign, segment, granule
        )

        self.intro_text = QtWidgets.QLabel(
            "".join(
                [
                    "Unable to find radargram in your filesystem. \n\n",
                    f"institution: {institution} \n",
                    f"campaign: {campaign} \n",
                    f"granule: {granule} \n\n",
                    "Expected to be at: \n",
                    str(granule_filepath),
                ]
            )
        )

        self.provider_widget = None
        if institution == "BAS":
            self.provider_widget = RadarViewerBASDownloadWidget(
                self.rootdir, region, institution, campaign, segment, granule
            )

        self.vbox_layout = QtWidgets.QVBoxLayout()
        self.vbox_layout.addWidget(self.intro_text)
        self.vbox_layout.addStretch(1)
        self.vbox_layout.addWidget(HorizontalLine())
        self.vbox_layout.addStretch(1)
        if self.provider_widget is None:
            QgsMessageLog.logMessage(
                f"BUG: Unable to help download data from {institution}, even though it should be supported"
            )
        else:
            self.provider_widget.closed.connect(self.close)
            self.vbox_layout.addWidget(self.provider_widget)
            # TODO: close this widget when the internal one's button is clicked?

        self.setLayout(self.vbox_layout)

    def run(self):
        QgsMessageLog.logMessage("RadarViewerDownloadWidget.run()")
        self.exec()


# TODO: This should probably have a base class, then derived ones that
#   change the text in the info label + how the download is performed.
class RadarViewerBASDownloadWidget(QtWidgets.QWidget):
    closed = QtCore.pyqtSignal()

    def __init__(self, rootdir, region, institution, campaign, segment, granule):
        super(RadarViewerBASDownloadWidget, self).__init__()
        QgsMessageLog.logMessage("initializing RadarViewerBASDownloadWidget")
        self.rootdir = rootdir
        self.region = region
        self.institution = institution
        self.campaign = campaign
        self.segment = segment
        self.granule = granule
        self.setup_ui()

    def download_clicked(self, _event):
        QgsMessageLog.logMessage("TODO: Actually download radargram!")
        self.closed.emit()

    def setup_ui(self):
        # TODO: The database needs to include file sizes, and where
        #   to download.
        transect_filesize = -1
        self.info_label = QtWidgets.QLabel(
            "".join(
                [
                    f"The requested transect is {transect_filesize} MB\n",
                    "And can be downloaded from: \n",
                    "TODO! ",
                ]
            )
        )

        self.cancel_pushbutton = QtWidgets.QPushButton("Cancel")
        self.cancel_pushbutton.clicked.connect(self.closed.emit)
        self.download_pushbutton = QtWidgets.QPushButton("Download")
        self.download_pushbutton.clicked.connect(self.download_clicked)

        self.button_hbox = QtWidgets.QHBoxLayout()
        self.button_hbox.addWidget(self.cancel_pushbutton)
        self.button_hbox.addStretch(1)
        self.button_hbox.addWidget(self.download_pushbutton)

        self.main_vbox = QtWidgets.QVBoxLayout()
        self.main_vbox.addWidget(self.info_label)
        self.main_vbox.addLayout(self.button_hbox)
        self.setLayout(self.main_vbox)


class HorizontalLine(QtWidgets.QFrame):
    def __init__(self):
        super(HorizontalLine, self).__init__()
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)


class VerticalLine(QtWidgets.QFrame):
    def __init__(self):
        super(VerticalLine, self).__init__()
        self.setFrameShape(QtWidgets.QFrame.VLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)
