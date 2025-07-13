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

import pathlib

import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as QtWidgets


class QIceRadarDialogs:
    """
    Various messages that we may need to display to the user.
    """

    issue_url = "https://github.com/qiceradar/qiceradar/issues/new"
    email_address = "qiceradar@gmail.com"

    @classmethod
    def display_unavailable_dialog(cls, institution: str, campaign: str) -> None:
        # TODO: Consider special case for BEDMAP1?
        msg = (
            "We have not found publicly-available radargrams for this transect."
            "<br><br>"
            f"Institution: {institution}"
            "<br>"
            f"Campaign: {campaign}"
            "<br><br>"
            "If these are now available, please let us know so we can update the database!"
            "<br><br>"
            f'Submit an issue: <a href="{cls.issue_url}">{cls.issue_url}</a>'
            "<br>"
            f'Or send us email: <a href="mailto:{cls.email_address}">{cls.email_address}</a>'
            "<br><br>"
            "If this is your data and you're thinking about releasing it, feel free to get in touch. We'd love to help if we can."
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    @classmethod
    def display_cannot_download_dialog(cls, granule_name: str) -> None:
        msg = (
            "This radargram is available, but we are not able to assist with downloading it."
            "<br><br>"
            f"Granule: {granule_name}"
            "<br><br>"
            "If this campaign is particularly important to your work, let us know! "
            "This feedback will help prioritize future development efforts. "
            "<br><br>"
            f'Submit an issue: <a href="{cls.issue_url}">{cls.issue_url}</a>'
            "<br>"
            f'Or send us email: <a href="mailto:{cls.email_address}">{cls.email_address}</a>'
            "<br>"
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    @classmethod
    def display_cannot_view_dialog(cls, granule_name: str) -> None:
        # TODO: Consider special case for information about Stanford's digitization efforts?
        # TODO: This may also be a prompt to update the code itself / present
        #   a link to the page documenting supported formats.
        msg = (
            "This radargram is available, but its format is not currently supported in the viewer "
            "<br><br>"
            f"Granule: {granule_name}"
            "<br><br>"
            "If this campaign is particularly important to your work, let us know! "
            "This feedback will help prioritize future development efforts. "
            "<br><br>"
            f'Submit an issue: <a href="{cls.issue_url}">{cls.issue_url}</a>'
            "<br>"
            f'Or send us email: <a href="mailto:{cls.email_address}">{cls.email_address}</a>'
            "<br>"
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    @classmethod
    def display_already_downloaded_dialog(cls, granule_name: str) -> None:
        # TODO: Should make this impossible by filtering the selection
        #   based on un-downloaded transects.
        #   I *could* make the unavailable impossible, but I want to display info
        #   about them, and a 3rd tooltip doesn't make sense.
        msg = f"Already downloaded requested data!<br>Granule: {granule_name}<br>"
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()

    @classmethod
    def display_must_download_dialog(
        cls, radargram_filepath: pathlib.Path, granule_name: str
    ) -> None:
        msg = (
            "Must download radargram before viewing it:"
            "<br>"
            f"Granule: {granule_name}"
            "<br><br>"
            "If you have already downloaded this data, check that the configured root directory is correct."
            "<br><br>"
            "Expected to find radargram at:"
            "<br>"
            f"{radargram_filepath}"
            "<br>"
        )
        message_box = QtWidgets.QMessageBox()
        message_box.setTextFormat(QtCore.Qt.RichText)
        message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        message_box.setText(msg)
        message_box.exec()
