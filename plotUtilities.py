# Not sure where this file belongs ... it's certainly not deva-specific, but
# I also don't see huge use for it elsewhere, unlike my data-wrangling code.

import PyQt5.QtWidgets as QtWidgets


def show_error_message_box(msg):
    # type: (str) -> None
    """
    Pops up dialog box with input message and waits for user to hit 'ok'.
    """
    msgbox = QtWidgets.QMessageBox()
    msgbox.setText(msg)
    msgbox.exec_()


def HLine():
    # type: () -> None
    """
    Creates a horizontal line that can be added to a layout.
    """
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Sunken)
    return line


def VLine():
    # type: () -> None
    """
    Creates a vertical line that can be added to a layout.
    """
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.VLine)
    line.setFrameShadow(QtWidgets.QFrame.Sunken)
    return line
