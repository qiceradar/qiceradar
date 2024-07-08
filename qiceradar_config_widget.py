import pathlib

import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets
import qgis.core
from qgis.core import QgsMessageLog
from qgis.gui import QgisInterface

from .qiceradar_config import UserConfig, config_is_valid, parse_config


# I wanted this to be a QDialog, but then a PushButton was ALWAYS welected,
# even if I had tabbed to a lineedit. This meant that hitting "enter" at tne
# end of editing would activate both child widgets, which is not desirable behaior.
# https://stackoverflow.com/questions/45288494/how-do-i-avoid-multiple-simultaneous-focus-in-pyside
# QUESTION: Does the iface argument wind up mattering? My other QDialog
#           popups don't have it, and it seems like it's not used.
class QIceRadarConfigWidget(QtWidgets.QDialog):

    # Useful so other dialogs that open this one can react
    # when it is closed.
    closed = QtCore.pyqtSignal()
    canceled = QtCore.pyqtSignal()
    config_saved = QtCore.pyqtSignal(UserConfig)

    def __init__(
        self,
        iface: QgisInterface,
        user_config: UserConfig,
    ) -> None:
        super().__init__()
        self.iface = iface
        self.setup_ui(user_config)

    def setup_ui(self, user_config: UserConfig) -> None:
        self.grid = QtWidgets.QGridLayout()

        datadir_row = 0
        nsidc_row = 1
        aad_row = 2
        button_row = 3

        self.datadir_label = QtWidgets.QLabel("Root data directory")
        self.datadir_question_button = QtWidgets.QPushButton("?")
        self.datadir_question_button.clicked.connect(
            self.datadir_question_button_clicked
        )

        self.datadir_set_button = QtWidgets.QPushButton("click to select directory")
        if user_config.rootdir is not None:
            self.datadir_set_button.setText(str(user_config.rootdir))
        self.datadir_set_button.clicked.connect(self.datadir_set_button_clicked)
        self.grid.addWidget(self.datadir_label, datadir_row, 0)
        self.grid.addWidget(self.datadir_question_button, datadir_row, 1)
        self.grid.addWidget(self.datadir_set_button, datadir_row, 2, 1, 3)

        # I think it's fine to store credentials in plain text; AWS's documentation
        # suggests that they do exactly that for most workflows. Just don't
        # check them in anywhere!
        # https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html
        self.nsidc_label = QtWidgets.QLabel("NSIDC credentials")
        self.nsidc_question_button = QtWidgets.QPushButton("?")
        self.nsidc_question_button.clicked.connect(self.nsidc_question_button_clicked)
        self.nsidc_credentials_label = QtWidgets.QLabel("credentials")
        self.nsidc_credentials_lineedit = QtWidgets.QLineEdit()
        if user_config.nsidc_credentials is not None:
            self.nsidc_credentials_lineedit.setText(user_config.nsidc_credentials)
        self.nsidc_credentials_lineedit.editingFinished.connect(
            self.nsidc_credentials_lineedit_editingfinished
        )
        self.nsidc_token_label = QtWidgets.QLabel("token")
        self.nsidc_token_lineedit = QtWidgets.QLineEdit()
        if user_config.nsidc_token is not None:
            self.nsidc_token_lineedit.setText(user_config.nsidc_token)
        self.nsidc_token_lineedit.editingFinished.connect(
            self.nsidc_token_lineedit_editingfinished
        )
        self.grid.addWidget(self.nsidc_label, nsidc_row, 0)
        self.grid.addWidget(self.nsidc_question_button, nsidc_row, 1)
        self.grid.addWidget(self.nsidc_credentials_label, nsidc_row, 2)
        self.grid.addWidget(self.nsidc_credentials_lineedit, nsidc_row, 3)
        self.grid.addWidget(self.nsidc_token_label, nsidc_row, 4)
        self.grid.addWidget(self.nsidc_token_lineedit, nsidc_row, 5)

        self.aad_label = QtWidgets.QLabel("AAD credentials")
        self.aad_question_button = QtWidgets.QPushButton("?")
        self.aad_question_button.clicked.connect(self.aad_question_button_clicked)
        self.aad_access_key_label = QtWidgets.QLabel("Access Key")
        self.aad_access_key_lineedit = QtWidgets.QLineEdit()
        if user_config.aad_access_key is not None:
            self.aad_access_key_lineedit.setText(user_config.aad_access_key)
        self.aad_access_key_lineedit.editingFinished.connect(
            self.aad_access_key_lineedit_editingfinished
        )
        self.aad_secret_key_label = QtWidgets.QLabel("Secret Key")
        self.aad_secret_key_lineedit = QtWidgets.QLineEdit()
        if user_config.aad_secret_key is not None:
            self.aad_secret_key_lineedit.setText(user_config.aad_secret_key)
        self.aad_secret_key_lineedit.editingFinished.connect(
            self.aad_secret_key_lineedit_editingfinished
        )
        self.grid.addWidget(self.aad_label, aad_row, 0)
        self.grid.addWidget(self.aad_question_button, aad_row, 1)
        self.grid.addWidget(self.aad_access_key_label, aad_row, 2)
        self.grid.addWidget(self.aad_access_key_lineedit, aad_row, 3)
        self.grid.addWidget(self.aad_secret_key_label, aad_row, 4)
        self.grid.addWidget(self.aad_secret_key_lineedit, aad_row, 5)

        # The Cancel button closes without saving.
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.canceled.emit)
        self.cancel_button.clicked.connect(self.close)
        # The OK button validates the file, then closes.
        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.clicked.connect(self.ok_button_clicked)
        self.grid.addWidget(self.cancel_button, button_row, 0)
        self.grid.addWidget(self.ok_button, button_row, 5)

        self.setLayout(self.grid)
        self.setWindowTitle("Configure QIceRadar")
        # I'm trying to get away from using a QDialog, but I'm not sure how to get
        # a QWidget to open a child window that's modal.
        # self.setWindowFlags(self.windowFlags() & QtCore.Qt.Window)
        # self.setWindowModality(QtCore.Qt.WindowModal)

    def datadir_question_button_clicked(self, _checked: bool) -> None:
        QgsMessageLog.logMessage("User clicked question button about data directory!")
        datadir_info = (
            "Root directory used by QIceRadar. \n\n "
            "All radargrams will be downloaded to and read from a directory structure created within this folder."
        )
        datadir_message_box = QtWidgets.QMessageBox()
        # NB: won't display on OSX
        datadir_message_box.setWindowTitle("Help: root directory")
        datadir_message_box.setText(datadir_info)
        datadir_message_box.exec()

    def datadir_set_button_clicked(self, _checked: bool) -> None:
        QgsMessageLog.logMessage("User clicked button to set data directory!")
        # TODO: Fill this in ... I can't find anything better than QFileDialog, which would be yet another modal window.
        file_dialog = QtWidgets.QFileDialog()
        file_dialog.setFileMode(QtWidgets.QFileDialog.Directory)
        result = file_dialog.exec()
        if result:
            filenames = file_dialog.selectedFiles()
            if len(filenames) > 1:
                errmsg = "This is a bug! QFileDialog should only allow selection of a single directory"
                QgsMessageLog.logMessage(errmsg)
            rootdir = filenames[0]
            QgsMessageLog.logMessage(
                f"File Dialog finished ... root directory = {rootdir}"
            )
            self.datadir_set_button.setText(rootdir)

    def nsidc_question_button_clicked(self, _checked: bool) -> None:
        QgsMessageLog.logMessage("User clicked NSIDC questions button")
        # Using rich text for the hyperlink forces using <br> rather than \n
        nsidc_info = (
            "Credentials for downloading data from NSIDC."
            "<br><br>"
            "A NASA EarthData login is necessary to download radargrams hosted at NSIDC. "
            "If you don't already have an account or don't want to configure this now, "
            "you will be prompted again when you attempt to download data hosted there."
            "<br><br>"
            "To create a free NASA EarthData login, go to "
            '<a href="https://urs.earthdata.nasa.gov/">https://urs.earthdata.nasa.gov/</a>'
        )
        nsidc_message_box = QtWidgets.QMessageBox()
        # NB: won't display on OSX
        nsidc_message_box.setWindowTitle("Help: NSIDC credentials")
        nsidc_message_box.setText(nsidc_info)
        nsidc_message_box.setTextFormat(QtCore.Qt.RichText)
        nsidc_message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)

        nsidc_message_box.exec()

    def nsidc_credentials_lineedit_editingfinished(self) -> None:
        QgsMessageLog.logMessage("User finished editing NSIDC credentials")

    def nsidc_token_lineedit_editingfinished(self) -> None:
        QgsMessageLog.logMessage("User finished editing NSIDC token")

    def aad_question_button_clicked(self, _checked: bool) -> None:
        QgsMessageLog.logMessage("User clicked AAD questions button")
        aad_info = (
            "Credentials for downloading ICECAP OIA radargrams from AAD"
            "<br><br>"
            "Larger datasets hosted by AAD require credentials for their S3 client. "
            "If you don't already have an account or don't want to configure this now, "
            "you will be prompted again when you attempt to download data hosted there."
            "<br><br>"
            "To obtain your credentials, follow the instructions at: "
            '<a href="https://data.aad.gov.au/dataset/5256/download">https://data.aad.gov.au/dataset/5256/download</a>'
        )
        aad_message_box = QtWidgets.QMessageBox()
        # NB: won't display on OSX
        # https://doc.qt.io/qtforpython-5/PySide2/QtWidgets/QMessageBox.html#PySide2.QtWidgets.PySide2.QtWidgets.QMessageBox.setWindowTitle
        # However, setWindowTitle does work for QDialog; could change to
        # that if it really matters.
        aad_message_box.setWindowTitle("Help: AAD credentials")
        aad_message_box.setText(aad_info)
        aad_message_box.setTextFormat(QtCore.Qt.RichText)
        aad_message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        aad_message_box.exec()

    def aad_access_key_lineedit_editingfinished(self) -> None:
        QgsMessageLog.logMessage("User finished editing AAD credentials")

    def aad_secret_key_lineedit_editingfinished(self) -> None:
        QgsMessageLog.logMessage("User finished editing AAD token")

    def ok_button_clicked(self, _checked: bool) -> None:
        QgsMessageLog.logMessage("User clicked OK")
        # read in all values; we want to return a configuration struct
        pp = pathlib.Path(self.datadir_set_button.text())
        if pp.is_dir():
            rootdir = pp
        else:
            rootdir = None

        ll = self.nsidc_credentials_lineedit.text().strip()
        if len(ll) > 0:
            nsidc_credentials = ll
        else:
            nsidc_credentials = None

        ll = self.nsidc_token_lineedit.text().strip()
        if len(ll) > 0:
            nsidc_token = ll
        else:
            nsidc_token = None

        ll = self.aad_access_key_lineedit.text().strip()
        if len(ll) > 0:
            aad_access_key = ll
        else:
            aad_access_key = None

        ll = self.aad_secret_key_lineedit.text().strip()
        if len(ll) > 0:
            aad_secret_key = ll
        else:
            aad_secret_key = None

        config = UserConfig(
            rootdir, nsidc_credentials, nsidc_token, aad_access_key, aad_secret_key
        )

        # If configuration isn't valid, we can't do anything useful.
        if config_is_valid(config):
            self.config_saved.emit(config)
            self.close()
        else:
            errmsg = "Please specify a valid directory for data"
            error_message_box = QtWidgets.QMessageBox()
            error_message_box.setText(errmsg)
            error_message_box.exec()
            return

    def close(self) -> bool:
        self.closed.emit()
        return super().close()

    def run(self) -> None:
        QgsMessageLog.logMessage("QIceRadarConfigWidget.run()")
        self.exec()
