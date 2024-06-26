import pathlib
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Callable, Dict

import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets
import requests  # for downloading files
from qgis.core import QgsMessageLog

from .qiceradar_config import UserConfig

# TODO: should have already been configured after download?
#     (I think this is meant to allow user to change config if
#     they discvoer it's necessary during a download attempt.)
from .qiceradar_config_widget import QIceRadarConfigWidget
from .radar_viewer_data_utils import get_granule_filepath


def format_bytes(filesize: int) -> str:
    filesize_kb = filesize / (1024)
    filesize_mb = filesize / (1024**2)
    filesize_gb = filesize / (1024**3)
    if filesize_gb > 1:
        filesize_str = f"{filesize_gb:0.1f} GB"
    elif filesize_mb > 1:
        filesize_str = f"{filesize_mb:0.1f} MB"
    elif filesize_kb > 1:
        filesize_str = f"{filesize_kb:0.1f} kB"
    else:
        filesize_str = f"{filesize} Bytes"
    return filesize_str


class DownloadConfirmationDialog(QtWidgets.QDialog):
    closed = QtCore.pyqtSignal()
    """
    Dialog box that shows user how large the download will be and
    where the file will be saved, before asking for confirmation to
    proceed.

    On confirmation, tells the DownloadMangerWidget to start handling
    a new transect (creating the DownloadManagerWidget if necessary.)
    """
    # TODO: This should be given all the info it needs;
    def __init__(
        self,
        config: UserConfig,
        config_cb: Callable[[UserConfig], None],
        attributes: Dict[str, str],
        database_file: str,
    ):
        super(DownloadConfirmationDialog, self).__init__()

        self.user_config = config
        self.set_config = config_cb
        self.attributes = attributes  # attributes from the feature
        self.database_file = database_file  # database with metadata

        # TODO: I think these maybe should be passed in? `attributes` is an
        #   awkward thing to pass around
        region = self.attributes["region"]
        self.institution = self.attributes["institution"]
        self.campaign = self.attributes["campaign"]
        segment = self.attributes["segment"]
        self.granule = self.attributes["granule"]
        # TODO: Look up data from granules table:
        # download_method
        # url
        # destination_path
        # filesize
        connection = sqlite3.connect(self.database_file)
        cursor = connection.cursor()
        # TODO: Constructing the granule_name like this is problematic;
        #   it should be passed around as the identifier.
        granule_name = f"{self.institution}_{self.campaign}_{self.granule}"
        sql_cmd = f"SELECT * FROM granules where name = '{granule_name}'"
        result = cursor.execute(sql_cmd)
        rows = result.fetchall()
        connection.close()
        # QUESTION: How do I want to log this? I need to figure out how these errors
        #    will propagate through the system.
        # TODO: I dislike this; setting to None requires checking for None later,
        #   rather than handling/propagating it right here.
        try:
            _, _, data_format, self.download_method, self.url, destination_path, self.filesize = rows[0]
        except:
            QgsMessageLog.logMessage(f"Invalid response {rows} from command {sql_cmd}")
            data_format, self.download_method, self.url, destination_path, self.filesize = None, None, None, None, None

        self.granule_filepath = pathlib.Path(self.user_config.rootdir, destination_path)

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
        QgsMessageLog.logMessage(f"Setting up download widget for feature with attributes: {self.attributes}")

        self.intro_text = QtWidgets.QLabel(
            "".join(
                [
                    "You requested download of: \n\n",
                    f"institution: {self.institution} \n",
                    f"campaign: {self.campaign} \n",
                    f"granule: {self.granule}",
                ]
            )
        )

        self.text_scroll = QtWidgets.QScrollArea()
        self.text_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.text_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        filesize_str = format_bytes(self.filesize)
        self.info_label = QtWidgets.QLabel(
            "".join(
                [
                    f"The requested segment is {filesize_str}.\n\n",
                    "It can be downloaded from: \n",
                    self.url,
                    "\n\n And will be saved to: \n",
                    str(self.granule_filepath),
                    "\n"
                ]
            )
        )
        self.info_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_scroll.setWidget(self.info_label)

        self.config_widget = QIceRadarConfigWidget(
            None, self.user_config, self.set_config
        )
        # TODO: I don't love this. Better to only create the config
        #   widget if/when needed. Add indirection via self.handle_config_button_clicked
        self.config_pushbutton = QtWidgets.QPushButton("Edit Config")
        self.config_pushbutton.clicked.connect(self.config_widget.run)
        # QUESTION: I'm not sure whether it's better to just start over, or
        #           try to update the config here. User would probably prefer
        #           being dumped back out into the download window, but getting
        #           the updated config isn't super clean.
        #           Easier to have them re-start.
        # TODO: I think this is a bit confusing; re-think this workflow
        #   and check how hard it would actually be to dump back into
        #   download dialog. (Tricky part is that changing the config
        #   will potentially change SO MUCH STATE, including whether
        #   a file even needs to be downloaded.)
        self.config_widget.config_saved.connect(self.close)

        self.cancel_pushbutton = QtWidgets.QPushButton("Cancel")
        # TODO: I'm confused by this ...
        self.cancel_pushbutton.clicked.connect(self.close)
        self.download_pushbutton = QtWidgets.QPushButton("Download")
        self.download_pushbutton.clicked.connect(self.download_clicked)

        self.button_hbox = QtWidgets.QHBoxLayout()
        self.button_hbox.addWidget(self.cancel_pushbutton)
        self.button_hbox.addWidget(self.config_pushbutton)
        self.button_hbox.addStretch(1)
        self.button_hbox.addWidget(self.download_pushbutton)

        self.vbox_layout = QtWidgets.QVBoxLayout()
        self.vbox_layout.addWidget(self.intro_text)
        self.vbox_layout.addStretch(1)
        self.vbox_layout.addWidget(HorizontalLine())
        self.vbox_layout.addStretch(1)
        self.vbox_layout.addWidget(self.text_scroll)
        self.vbox_layout.addStretch(1)
        self.vbox_layout.addLayout(self.button_hbox)

        self.setLayout(self.vbox_layout)
        self.setWindowTitle("Download Data")

    def run(self):
        QgsMessageLog.logMessage("DownloadConfirmationDialog.run()")
        self.exec()

    def download_clicked(self, _event):
        # TODO: remove below mkdir after making sure it's in the other widgets
        self.granule_filepath.parents[0].mkdir(parents=True, exist_ok=True)
        QgsMessageLog.logMessage("TODO: Actually download radargram!")
        self.closed.emit()


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
