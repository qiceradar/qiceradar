# Copyright 2022-2025 Laura Lindzey, UW-APL
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
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

import copy
import os
import pathlib
import shutil
import tempfile
from typing import Dict, Optional

import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
import requests  # for downloading files
from PyQt5.QtCore import Qt
from qgis.core import QgsMessageLog
from qgis.gui import QgisInterface


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
    # Emitted when user wants to update configuration
    configure = QtCore.pyqtSignal()
    download_confirmed = QtCore.pyqtSignal()
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
        dest_filepath: pathlib.Path,
        institution: str,
        campaign: str,
        granule_name: str,
        download_method: str,
        url: str,
        filesize: int,
    ) -> None:
        super(DownloadConfirmationDialog, self).__init__()

        self.dest_filepath = dest_filepath
        self.institution = institution
        self.campaign = campaign
        self.granule_name = granule_name

        self.download_method = download_method
        self.url = url
        self.filesize = filesize

        # TODO: We need to check whether the full granule_filepath can be created
        #  If not, should pop up box with error, whose 'OK' button pops up config
        #  widget.
        #  I think that logic may fit better elsewhere, though one option would
        #  be to check it when the "Download" button is pressed.
        self.setup_ui()

    def setup_ui(self) -> None:
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

        self.intro_text = QtWidgets.QLabel(
            "".join([
                "You requested download of: \n\n",
                f"{self.granule_name}",
            ])
        )

        self.text_scroll = QtWidgets.QScrollArea()
        self.text_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.text_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        filesize_str = format_bytes(self.filesize)
        self.info_label = QtWidgets.QLabel(
            "".join([
                f"The requested segment is {filesize_str}.\n\n",
                "It can be downloaded from: \n",
                self.url,
                "\n\n And will be saved to: \n",
                str(self.dest_filepath),
                "\n",
            ])
        )
        self.info_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.text_scroll.setWidget(self.info_label)

        # TODO: I don't love this. Better to only create the config
        #   widget if/when needed. Add indirection via self.handle_config_button_clicked
        self.config_pushbutton = QtWidgets.QPushButton("Edit Config")
        # This ordering matters! Want to close this widget before
        # popping up the next one.
        # Config changes state enough that we force user to re-start the
        # download widget from the beginning.
        self.config_pushbutton.clicked.connect(self.close)
        self.config_pushbutton.clicked.connect(self.configure.emit)

        self.cancel_pushbutton = QtWidgets.QPushButton("Cancel")
        self.cancel_pushbutton.clicked.connect(self.close)
        self.download_pushbutton = QtWidgets.QPushButton("Download")
        self.download_pushbutton.clicked.connect(self.close)
        self.download_pushbutton.clicked.connect(self.download_confirmed.emit)

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

    def run(self) -> None:
        self.exec()


class HorizontalLine(QtWidgets.QFrame):
    def __init__(self) -> None:
        super(HorizontalLine, self).__init__()
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)


class VerticalLine(QtWidgets.QFrame):
    def __init__(self) -> None:
        super(VerticalLine, self).__init__()
        self.setFrameShape(QtWidgets.QFrame.VLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)


class DownloadWindow(QtWidgets.QMainWindow):
    download_finished = QtCore.pyqtSignal()

    def __init__(self, iface: QgisInterface) -> None:
        super().__init__()
        self.iface = iface
        self.setWindowTitle("QIceRadar Radargram Downloader")
        self.setup_ui()

    def setup_ui(self) -> None:
        central_widget = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout()
        scroll = QtWidgets.QScrollArea()
        scroll_widget = QtWidgets.QWidget()
        self.scroll_vbox = QtWidgets.QVBoxLayout()
        self.scroll_vbox.addStretch(1)
        scroll_widget.setLayout(self.scroll_vbox)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_widget)
        # maps granule to widget
        self.download_widgets: Dict[str, DownloadWidget] = {}

        vbox.addWidget(scroll)
        central_widget.setLayout(vbox)
        self.setCentralWidget(central_widget)

    def download(
        self,
        granule: str,
        url: str,
        destination_filepath: pathlib.Path,
        filesize: int,
        headers: Dict[str, str],
    ) -> None:
        # TODO: This means that once a download has been canceled, you won't
        #   be able to retry it until the plugin is reloaded.
        # Consider allowing multiple downloads? (or adding a "retry" button?)
        if granule in self.download_widgets:
            if (
                self.download_widgets[granule].canceled
                or self.download_widgets[granule].failed
            ):
                # OK, we can retry
                QgsMessageLog.logMessage(f"Retrying download of {granule}")
            elif self.download_widgets[granule].finished:
                QgsMessageLog.logMessage(f"Already downloaded {granule}")
                return
            else:
                print(f"Currently downloading {granule}")
                return

        print(f"Downloading {granule}")
        widget = DownloadWidget(granule, url, filesize, destination_filepath, headers)
        self.download_widgets[granule] = widget
        self.download_widgets[granule].download_finished.connect(
            self.download_finished.emit
        )
        widget.run()
        self.scroll_vbox.insertWidget(0, widget)


class DownloadWidget(QtWidgets.QWidget):
    download_finished = QtCore.pyqtSignal()
    """
    Widget in charge of downloading a single granule.
    """
    request_pause = QtCore.pyqtSignal()
    request_resume = QtCore.pyqtSignal()
    request_cancel = QtCore.pyqtSignal()

    def __init__(
        self,
        granule: str,
        url: str,
        filesize: int,
        destination_filepath: pathlib.Path,
        headers: Dict[str, str],
    ) -> None:
        super().__init__()
        self.granule = granule
        self.url = url
        self.filesize = filesize
        self.headers = headers
        self.destination_filepath = destination_filepath
        self.canceled = False
        self.failed = False
        self.finished = False

        self.help_msg = (
            "You can manually download this radargram (e.g. using Chrome) from: \n\n"
            f"{self.url}\n\n"
            "and save it to: \n\n"
            f"{self.destination_filepath}"
        )

        self.setup_ui()

    def setup_ui(self) -> None:
        # I don't love this -- I'm changing the background color so the
        # widgets will be visually distinguishable when put in the scroll area
        # Using white with alpha = 25 to make it slightly lighter than the background
        self.setAutoFillBackground(True)
        pp = self.palette()
        pp.setColor(self.backgroundRole(), QtGui.QColor(255, 255, 255, 25))
        self.setPalette(pp)

        # arg order is horizontal, vertical
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout()
        # TODO: When porting to QGIS, use
        # icon = QgsApplication.getThemeIcon("/mActionFileOpen.svg")
        # which returns a QIcon
        # pixmap = icon.pixmap(QtCore.QSize(20, 20))
        # label.setPixmap(pixmap)

        # ALSO need to have a status field at left of widget
        # mTaskComplete.svg (for finished successfully)
        # mTaskOnHold.svg (for paused)
        # mTaskTerminated.svg  (for failed)
        # mTaskRunning.svg
        # mTaskCancel.svg (for user canceled)
        self.status_label = QtWidgets.QLabel("Downloading")
        self.granule_label = QtWidgets.QLabel(self.granule)
        self.progress_label = QtWidgets.QLabel("0 / 0")
        self.percent_label = QtWidgets.QLabel("(0%)")
        self.progress_bar = QtWidgets.QProgressBar()
        # We provide our own, more precise, label
        self.progress_bar.setTextVisible(False)
        # The QProgressBar only supports up to 32-bit signed ints,
        # which isn't enough for some of our > 3GB file sizes!
        # So, we'll plot 100*percent_finished, rather than bytes.
        self.progress_bar.setRange(0, 100 * 100)

        # mIconTimerPause.svg
        # mActionPlay.svg
        # mTaskCancel.svg
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.resume_button = QtWidgets.QPushButton("Resume")
        self.resume_button.setEnabled(False)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.help_button = QtWidgets.QPushButton("?")

        self.pause_button.clicked.connect(self.handle_pause_button_clicked)
        self.resume_button.clicked.connect(self.handle_resume_button_clicked)
        self.cancel_button.clicked.connect(self.handle_cancel_button_clicked)
        self.help_button.clicked.connect(self.handle_help_button_clicked)

        # Trying to reduce jitter by using fixed-width font.
        # Unfortunately, this doesn't eem to work on OSX, and I found a mention
        # that since X11 doesn't make this info available to Qt, style hinting
        # won't work. Instead, setting the family seemed to work.
        # TODO: Confirm that this works on Windows & Linux
        font = self.progress_label.font()
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setFamily("Mono")
        self.progress_label.setFont(font)

        font = self.percent_label.font()
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setFamily("Mono")
        self.percent_label.setFont(font)

        layout.addWidget(self.status_label)
        layout.addWidget(self.granule_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.percent_label)
        # TODO: figure out how to get
        # layout.addWidget(self.pause_button)
        # layout.addWidget(self.resume_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.help_button)
        self.setLayout(layout)

    def handle_progress(self, progress: int) -> None:
        # print(f"DownloadWidget.handle_progress({progress})")
        msg = f"{format_bytes(progress)} / {format_bytes(self.filesize)}"
        self.progress_label.setText(msg)
        pct = 100.0 * progress / self.filesize
        self.percent_label.setText(f"({pct:0.1f}%)")
        self.progress_bar.setValue(int(100 * pct))

    def handle_paused(self) -> None:
        # TODO: this should become an icon
        self.status_label.setText("Paused")
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def handle_resumed(self) -> None:
        # TODO: this should become an icon
        self.status_label.setText("Resumed")
        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def handle_finished(self) -> None:
        self.finished = True
        print("DownloadWidget.handle_finished")
        # TODO: this should become an icon
        self.status_label.setText("Finished")
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        pp = self.palette()
        pp.setColor(self.backgroundRole(), QtGui.QColor(0, 0, 0, 25))
        self.setPalette(pp)
        self.download_finished.emit()

    def handle_failed(self, err_msg: str) -> None:
        self.failed = True
        # TODO: this should become an icon
        self.status_label.setText("Failed")
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        pp = self.palette()
        pp.setColor(self.backgroundRole(), QtGui.QColor(0, 0, 0, 25))
        self.setPalette(pp)
        # TODO: Update help button text with the information? Will probably need a scroll bar...
        self.help_msg = "".join([
            self.help_msg,
            "\n\n\n ------------- DOWNLOAD FAILED -----------\n\n\n",
            err_msg,
        ])

    def handle_canceled(self) -> None:
        self.canceled = True
        # TODO: this should become an icon
        self.status_label.setText("Canceled")
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

        font = self.granule_label.font()
        font.setStrikeOut(True)
        self.granule_label.setFont(font)

        pp = self.palette()
        pp.setColor(self.backgroundRole(), QtGui.QColor(0, 0, 0, 25))
        # bright-ish red
        pp.setColor(QtGui.QPalette.WindowText, QtGui.QColor(194, 6, 18))

        self.setPalette(pp)

    def run(self) -> None:
        self.download_worker_thread = QtCore.QThread()
        self.worker = DownloadWorker(self.url, self.headers, self.destination_filepath)
        self.worker.moveToThread(self.download_worker_thread)

        self.download_worker_thread.started.connect(self.worker.run)
        # QUESTION: I'm not clear on how this differs from the worker ones.
        self.download_worker_thread.finished.connect(
            self.download_worker_thread.deleteLater
        )
        # self.thread.finished.connect(self.handle_thread_finished)

        # Hook up signals from the worker to updates in the widget
        self.worker.paused.connect(self.handle_paused)
        self.worker.resumed.connect(self.handle_resumed)
        self.worker.canceled.connect(self.handle_canceled)
        self.worker.failed.connect(self.handle_failed)
        self.worker.finished.connect(self.handle_finished)
        self.worker.progress.connect(self.handle_progress)

        # For canceled & failed, we won't revisit the download worker thread,
        # so can clean up
        self.worker.finished.connect(self.download_worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.download_worker_thread.quit)
        self.worker.failed.connect(self.worker.deleteLater)

        # Hook up signals between the buttons in this widget and the worker.
        self.request_pause.connect(self.worker.pause_download)
        self.request_resume.connect(self.worker.resume_download)
        self.request_cancel.connect(self.worker.cancel_download)

        self.download_worker_thread.start()

    def handle_pause_button_clicked(self) -> None:
        print(f"User paused download for granule {self.granule}")
        self.request_pause.emit()

    def handle_resume_button_clicked(self) -> None:
        print(f"User resumed download for granule {self.granule}")
        self.request_resume.emit()
        # self.worker.resume()

    def handle_cancel_button_clicked(self) -> None:
        print(f"User canceled download for granule {self.granule}")
        self.request_cancel.emit()

    def handle_help_button_clicked(self) -> None:
        message_box = QtWidgets.QMessageBox()
        message_box.setText(self.help_msg)
        message_box.exec()


class DownloadWorker(QtCore.QObject):
    """
    The DownloadWorker class actually handles the download.
    """

    paused = QtCore.pyqtSignal()
    resumed = QtCore.pyqtSignal()  # Also emitted on "running"
    finished = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)  # Contains traceback of exception, as str
    canceled = QtCore.pyqtSignal()
    # Qt's signals use an int32 if I specify "int" here, so use "object"
    progress = QtCore.pyqtSignal(object)

    def __init__(
        self, url: str, headers: Dict[str, str], destination_filepath: pathlib.Path
    ) -> None:
        super().__init__()
        self.url = url
        self.headers = headers
        self.destination_filepath = destination_filepath
        self.pause_requested = False
        self.resume_requested = False
        self.cancel_requested = False
        self.downloading = False
        self.bytes_received = 0
        self.if_range: Optional[str] = None
        self.timeout = 10  # TODO: Up this for production
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        print(f"DownloadWorker saving to {self.temp_file.name}")

    def resume_download(self) -> None:
        self.resumed.emit()
        self.run()

    def run(self) -> None:
        """
        When I requested a "resume" a large part of the way through
        requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='ramadda.data.bas.ac.uk', port=443): Read timed out. (read timeout=10)
        """
        if self.downloading:
            print("Error! called run() when worker is already running.")
            return
        # This is needed in order to use the same function for
        self.pause_requested = False
        print("DownloadWorker.run()")
        # At least for BAS's data center, Accept-Ranges is set in GET but not HEAD,
        # so we can't check ahead of time whether to expect the Range to work.
        req_headers = copy.deepcopy(self.headers)
        if self.bytes_received > 0 and self.if_range is not None:
            req_headers["Range"] = f"bytes={self.bytes_received}-"
            req_headers["If-Range"] = self.if_range

        try:
            # TODO: I'm not sure why I can't get resuming a download to work.
            #    I've tested that BAS supports resuming using Chrome.
            #    Leaving this in here for now, since it correctly detects
            #    that we're starting from scratch.
            print(f"calling requests.get with headers={req_headers}")
            req = requests.get(
                self.url, stream=True, headers=req_headers, timeout=self.timeout
            )
            if "Last-Modified" in req.headers:
                self.if_range = req.headers["Last-Modified"]
                print(f"Got Last-Modified: {self.if_range} ")
            else:
                print(f"Could not find last-modified. Huh. Headers = {req.headers}")
        except Exception as ex:
            QgsMessageLog.logMessage("DownloadWorker.run got exception!")
            QgsMessageLog.logMessage(ex)
            self.failed.emit(str(ex))
            return

        print(f"Request status code: {req.status_code}")
        print(f"GET headers: {req.request.headers}")
        if req.status_code == 200:
            QgsMessageLog.logMessage(f"Starting download of {self.url}")
            resuming = False
        elif req.status_code == 206:
            QgsMessageLog.logMessage(f"Resuming download of {self.url}")
            resuming = True
        else:
            msg = f"Download failed! Code {req.status_code}, url: {self.url}"
            QgsMessageLog.logMessage(msg)
            self.failed.emit(msg)
            return

        self.downloading = True
        self.download(req, resuming)

    def download(self, req: requests.Response, resuming: bool) -> None:
        """
        urllib3.exceptions.ProtocolError: ('Connection broken: IncompleteRead(252794542 bytes read, 266366111 more expected)', IncompleteRead(252794542 bytes read, 266366111 more expected))
        """
        chunk_size = 4096
        # Only append to temp file if we can resume download partway through.
        # If range requests are not supported, then have to start from the beginning again
        if resuming:
            permissions = "ab"
        else:
            permissions = "wb"
            self.bytes_received = 0

        with open(self.temp_file.name, permissions) as fp:
            try:
                for chunk in req.iter_content(chunk_size):
                    # processing events here means that if the download has hung,
                    # we won't be able to cancel it until the next chunk comes
                    # through (this isn't an interruption...)
                    QtWidgets.QApplication.processEvents()
                    if self.cancel_requested or self.pause_requested:
                        break
                    self.bytes_received += len(chunk)
                    fp.write(chunk)
                    self.progress.emit(self.bytes_received)
            except requests.exceptions.ChunkedEncodingError as ex:
                # I saw this error once; however, I'm not sure how to generate it again to test it.
                # If there was any data in flight, would need to somehow
                # recover it before continuing.
                # https://stackoverflow.com/questions/44509423/python-requests-chunkedencodingerrore-requests-iter-lines
                print("DownloadWorker.download: ChunkedEncodingError.")
                print(ex)
                raise ex from None  # Re-raise because we don't handle it yet
            except requests.exceptions.ReadTimeout as ex:
                print("DownloadWorker.download: ReadTimeout.")
                print(ex)
                # Pausing so user can re-try.
                # Would it be better to make use of the existing
                # machinery for pausing, and just set
                # self.pause_requested = True ??
                self.paused.emit()
                self.downloading = False
                return

            except Exception as ex:
                print("DownloadWorker.download")
                print(ex)
                self.failed.emit(str(ex))

        if self.cancel_requested:
            self.canceled.emit()
        elif self.pause_requested:
            self.paused.emit()
        else:
            print(
                f"DownloadWorker finished! Moving data to {self.destination_filepath}"
            )
            try:
                shutil.move(self.temp_file.name, self.destination_filepath)
            except Exception as move_ex:
                QgsMessageLog.logMessage("Unable to move file; trying to copy.")
                # On one beta tester's Windows machine, we got the error:
                # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process
                # So, in this case, just try copying
                try:
                    # On another beta tester's machine, this failed partway through copying a 3G file.
                    # In that case, I want to remove the half-copied file, and give them a warning.
                    shutil.copy(self.temp_file.name, self.destination_filepath)
                except Exception as copy_ex:
                    if os.path.isfile(self.destination_filepath):
                        os.remove(self.destination_filepath)
                    error_msg = str(move_ex) + "\n\n\n" + str(copy_ex)
                    self.failed.emit(error_msg)

            self.finished.emit()
        self.downloading = False

    def pause_download(self) -> None:
        print("DownloadWorker: pause_download")
        self.pause_requested = True

    def cancel_download(self) -> None:
        print("DownloadWorker: cancel_download")
        self.cancel_requested = True
