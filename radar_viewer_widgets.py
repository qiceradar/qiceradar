# Copyright 2022-2024 Laura Lindzey, UW-APL
#           2015-2018 Laura Lindzey, UTIG
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


import itertools
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib
import numpy as np
import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# This was added in matplotlib 3.4, but even in 2024 the MacOS QGIS install
# is shipping with matplotlib 3.3 (Ubuntu debs + Windows install have updated)
try:
    from matplotlib.widgets import RangeSlider
    RANGE_SLIDER_SUPPORTED = True
except ImportError:
    from matplotlib.widgets import Slider
    RANGE_SLIDER_SUPPORTED = False

from .plotutils.pyqt_utils import show_error_message_box


class ScalebarControls(QtWidgets.QWidget):
    """
    Widget that provides checkbox to enable/disable scalebar,
    along with controls setting its length and position.
    """
    # Emitted when the checkbox changes; argument is enabled / not
    checked = QtCore.pyqtSignal(bool)
    # Emitted when user updates length; argument is length in meters
    new_length = QtCore.pyqtSignal(float)
    # Emitted when user updates origin; argument is x_fraction, y_fraction
    new_origin = QtCore.pyqtSignal(float, float)

    def __init__(
        self,
        initial_value: float, # Initial value for the scalebar length
        label: str, # Label for the checkbox. Usually "Horizontal" or "Vertical"
        unit_label: str, # Label for length units
        x0: float, # Initial X position for scalebar (in fraction of axis)
        y0: float, # Initial Y position for scalebar (in fraction of axis)
    ) -> None:
        # ConfigWidget doesnt' ahve parent, but DoubleSlider does.
        # Do we need to?
        super().__init__()
        self.initial_value = initial_value
        self.label = label
        self.unit_label = unit_label
        self.x0 = x0
        self.y0 = y0

        self.setup_ui()

    def setup_ui(self) -> None:

        self.checkbox = QtWidgets.QCheckBox(f"{self.label}")
        self.checkbox.clicked.connect(
            lambda val: self.checked.emit(val)
        )

        self.length_label = QtWidgets.QLabel(f"Length: ({self.unit_label})")

        self.length_lineedit = QtWidgets.QLineEdit()
        self.length_validator = QtGui.QDoubleValidator()
        self.length_validator.setBottom(0.0)
        self.length_validator.setDecimals(2)
        self.length_lineedit.setValidator(self.length_validator)
        # TODO: Originally, this was editingFinished, but I wanted a
        #  signal that has an argument with the current text. Confirm
        #  that this works as intended (only fires for valid input)
        self.length_lineedit.editingFinished.connect(
            self.send_new_length
        )
        self.length_lineedit.setText(f"{self.initial_value:.2f}")
        self.length_lineedit.setMinimumWidth(50)
        self.length_lineedit.setMaximumWidth(60)

        self.origin_label = QtWidgets.QLabel(
            "origin (x, y):"
        )

        self.x0_lineedit = QtWidgets.QLineEdit()
        self.origin_validator = QtGui.QDoubleValidator()
        self.origin_validator.setBottom(0.0)
        self.origin_validator.setTop(1.0)
        self.origin_validator.setDecimals(2)

        self.x0_lineedit.setValidator(self.origin_validator)
        self.x0_lineedit.setText(f"{self.x0:0.2f}")
        self.x0_lineedit.setMinimumWidth(30)
        self.x0_lineedit.setMaximumWidth(40)

        self.y0_lineedit = QtWidgets.QLineEdit()
        self.y0_lineedit.setValidator(self.origin_validator)
        self.y0_lineedit.setText(f"{self.y0:0.2f}")
        self.y0_lineedit.setMinimumWidth(30)
        self.y0_lineedit.setMaximumWidth(40)

        # Must happen after setting the text ...
        self.x0_lineedit.editingFinished.connect(
            self.send_new_origin
        )
        self.y0_lineedit.editingFinished.connect(
            self.send_new_origin
        )

        self.length_hbox = QtWidgets.QHBoxLayout()
        self.length_hbox.addWidget(self.length_label)
        self.length_hbox.addWidget(self.length_lineedit)
        self.length_hbox.addStretch(1)

        self.origin_hbox = QtWidgets.QHBoxLayout()
        self.origin_hbox.addStretch(1)
        self.origin_hbox.addWidget(self.origin_label)
        self.origin_hbox.addWidget(self.x0_lineedit)
        self.origin_hbox.addWidget(self.y0_lineedit)

        self.vbox = QtWidgets.QVBoxLayout()
        self.vbox.addWidget(self.checkbox)
        self.vbox.addLayout(self.length_hbox)
        self.vbox.addLayout(self.origin_hbox)

        self.setLayout(self.vbox)

    def send_new_origin(self):
        x0 = float(self.x0_lineedit.text())
        y0 = float(self.y0_lineedit.text())
        self.new_origin.emit(x0, y0)

    def send_new_length(self):
        length = float(self.length_lineedit.text())
        self.new_length.emit(length)



class DoubleSlider(QtWidgets.QWidget):
    """
    Widget that provides textboxes and sliders to update the min/max
    value for a range.
    * Does not force textbox values to be within the range of the bar.
      (in practice, we set the bar range based on image extrema, but sometimes
      you want to use consistent limits across radargrams.)
    * does force minval <= maxval
    """

    def __init__(
        self,
        parent: Optional[Any] = None,
        new_lim_cb=None,
        curr_lim: Tuple[float, float] = (0.0, 1.0),
    ):
        super(DoubleSlider, self).__init__(parent)
        self.parent = parent
        """
        * new_lim_cb([min,max]) - callback to call whenever either side
          of the limit changes.
        """
        self.new_lim_cb = new_lim_cb

        self.curr_lim = curr_lim

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        # TODO - have sliders only call update when _released_,
        # otherwise it may try to redraw the image tons.
        # (In practice, doesn't seem terrible)


        self.slider_fig = Figure((1, 1))
        self.slider_canvas = FigureCanvas(self.slider_fig)
        self.slider_canvas.setParent(self)

        # Want the canvas + figure to blend in with Qt Widget, rather
        # than standing out with a white background
        palette = QtGui.QGuiApplication.palette()
        qt_color = palette.window().color()
        mpl_color = [qt_color.redF(), qt_color.greenF(), qt_color.blueF(), qt_color.alphaF()]
        self.slider_fig.patch.set_facecolor(mpl_color)  # This is what did it

        # Unfortunately, the on_changed events don't only fire when the mouse
        # is released, but that seems to cause minimal enough redraw to not
        # present a huge problem.
        slider_label = None
        if RANGE_SLIDER_SUPPORTED:
            # Can't use full xlim because the slider handles will go off the sides
            self.slider_ax = self.slider_fig.add_axes([0.03, 0, 0.94, 1])
            self.range_slider = RangeSlider(
                self.slider_ax, slider_label, curr_lim[0], curr_lim[1], valfmt=None
            )
            self.range_slider.on_changed(self._on_range_slider_changed)
            # This works, but then the highlighted region is too tall.
            # I also don't like reaching into the class to change attributes like this
            # self.range_slider.track.set_height(0.25)
            self.slider_canvas.setFixedHeight(15)
        else:
            # Can't use full xlim because the slider handles will go off the sides
            self.slider_ax1 = self.slider_fig.add_axes([0.03, 0.5, 0.94, 1])
            self.slider_ax2 = self.slider_fig.add_axes([0.03, 0.0, 0.94, 0.5])

            self.min_range_slider = Slider(self.slider_ax1, slider_label, curr_lim[0], curr_lim[1], valinit=curr_lim[0], valfmt=None)
            self.min_range_slider.on_changed(self._on_min_range_slider_changed)
            self.max_range_slider = Slider(self.slider_ax2, slider_label, curr_lim[0], curr_lim[1], valinit=curr_lim[1], valfmt=None)
            self.max_range_slider.on_changed(self._on_max_range_slider_changed)
            self.slider_canvas.setFixedHeight(30)

        self.slider_widget = QtWidgets.QWidget()
        self.slider_layout = QtWidgets.QHBoxLayout()
        self.slider_layout.addWidget(self.slider_canvas)
        self.slider_widget.setLayout(self.slider_layout)
        self.slider_widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        # These labels are for min/max val in image
        self.slider_min_label = QtWidgets.QLabel(f"{self.curr_lim[0]:.2f}")
        self.slider_max_label = QtWidgets.QLabel(f"{self.curr_lim[1]:.2f}")
        self.slider_hbox = QtWidgets.QHBoxLayout()
        self.slider_hbox.addWidget(self.slider_min_label)
        self.slider_hbox.addStretch(1)
        self.slider_hbox.addWidget(self.slider_max_label)

        self.slider_set_min_label = QtWidgets.QLabel("MIN")
        self.min_slider_textbox = QtWidgets.QLineEdit()
        self.min_slider_textbox.setMinimumWidth(90)
        self.min_slider_textbox.setMaximumWidth(120)
        self.min_slider_textbox.setText(f"{self.curr_lim[0]}")
        self.min_slider_textbox.editingFinished.connect(
            self._on_min_slider_textbox_edited,
        )
        set_min_slider_hbox = QtWidgets.QHBoxLayout()
        set_min_slider_hbox.addWidget(self.slider_set_min_label)
        set_min_slider_hbox.addStretch(1)
        set_min_slider_hbox.addWidget(self.min_slider_textbox)

        self.slider_set_max_label = QtWidgets.QLabel("MAX")
        self.max_slider_textbox = QtWidgets.QLineEdit()
        self.max_slider_textbox.setMaximumWidth(90)
        self.max_slider_textbox.setMaximumWidth(120)
        self.max_slider_textbox.setText(f"{self.curr_lim[1]:.1f}")
        self.max_slider_textbox.editingFinished.connect(
            self._on_max_slider_textbox_edited,
        )
        set_max_slider_hbox = QtWidgets.QHBoxLayout()
        set_max_slider_hbox.addWidget(self.slider_set_max_label)
        set_max_slider_hbox.addStretch(1)
        set_max_slider_hbox.addWidget(self.max_slider_textbox)

        self.layout.addLayout(set_min_slider_hbox)
        self.layout.addLayout(set_max_slider_hbox)
        self.layout.addWidget(self.slider_widget)
        self.layout.addLayout(self.slider_hbox)

    def set_range(self, lim: Tuple[float, float]) -> None:
        """
        Resetting the range of the slider automatically sets it to
        be at the full range.
        Does not trigger any callbacks.
        """
        rmin, rmax = lim
        # Create new RangeSlider since valmin/valmax can't be changed via the API
        slider_label = None
        if RANGE_SLIDER_SUPPORTED:
            self.range_slider = matplotlib.widgets.RangeSlider(
                self.slider_ax, slider_label, lim[0], lim[1], valinit=lim, valfmt=None
            )
            self.range_slider.on_changed(self._on_range_slider_changed)
        else:
            self.min_range_slider = Slider(
                self.slider_ax1, slider_label, lim[0], lim[1], valinit=lim[0], valfmt=None
            )
            self.min_range_slider.on_changed(self._on_min_range_slider_changed)
            self.max_range_slider = Slider(
                self.slider_ax2, slider_label, lim[0], lim[1], valinit=lim[1], valfmt=None
            )
            self.max_range_slider.on_changed(self._on_max_range_slider_changed)
        self.slider_min_label.setText(f"{rmin:.2f}")
        self.slider_max_label.setText(f"{rmax:.2f}")
        self.set_value(lim)

    def set_value(self, lim: Tuple[float, float]) -> None:
        """
        Updates the slider values, w/o changing their range.
        Does not trigger callbacks.
        """
        self.curr_lim = lim
        rmin, rmax = lim
        self.max_slider_textbox.setText(f"{rmax:.2f}")
        self.min_slider_textbox.setText(f"{rmin:.2f}")

    def _on_min_slider_textbox_edited(self) -> None:
        # TODO(lindzey): would be cleaner to do input validation here
        min_text = self.min_slider_textbox.text()
        try:
            input_min = float(min_text)
            self.update_min_value(input_min)
        except Exception as ex:
            print("Unable to set min to: {min_text}")
            print(ex)

    def update_min_value(self, input_min: float) -> None:
        # min can't be bigger than max
        cmin = min(self.curr_lim[1], input_min)
        self.min_slider_textbox.setText(f"{cmin:.2f}")
        self.curr_lim = (cmin, self.curr_lim[1])
        if RANGE_SLIDER_SUPPORTED:
            self.range_slider.set_val(self.curr_lim)
        else:
            self.min_range_slider.set_val(cmin)
        if self.new_lim_cb is not None:
            self.new_lim_cb(self.curr_lim)

    def _on_range_slider_changed(self, newlim) -> None:
        # print(f"Called _on_range_slider_changed with newlim = {newlim}")
        self.min_slider_textbox.setText(f"{newlim[0]:.2f}")
        self.max_slider_textbox.setText(f"{newlim[1]:.2f}")
        self.curr_lim = newlim
        if self.new_lim_cb is not None:
            self.new_lim_cb(self.curr_lim)

    def _on_min_range_slider_changed(self, newmin) -> None:
        # print(f"Called _on_min_range_slider_changed with newlim = {newmin}")
        self.min_slider_textbox.setText(f"{newmin:.2f}")
        curr_max = float(self.max_slider_textbox.text())
        self.curr_lim = [newmin, curr_max]
        if self.new_lim_cb is not None:
            self.new_lim_cb(self.curr_lim)

    def _on_max_range_slider_changed(self, newmax) -> None:
        # print(f"Called _on_max_range_slider_changed with newlim = {newmax}")
        self.max_slider_textbox.setText(f"{newmax:.2f}")
        curr_min = float(self.min_slider_textbox.text())
        self.curr_lim = [curr_min, newmax]
        if self.new_lim_cb is not None:
            self.new_lim_cb(self.curr_lim)

    def _on_max_slider_textbox_edited(self) -> None:
        max_text = self.max_slider_textbox.text()
        try:
            input_max = float(max_text)
            self.update_max_value(input_max)
        except Exception as ex:
            print("Unable to set maxx to: {max_text}")
            print(ex)

    def update_max_value(self, input_max: float) -> None:
        # max can't be smaller than min
        cmax = max(self.curr_lim[0], input_max)
        self.max_slider_textbox.setText(f"{cmax:.2f}")
        self.curr_lim = (self.curr_lim[0], cmax)
        if RANGE_SLIDER_SUPPORTED:
            self.range_slider.set_val(self.curr_lim)
        else:
            self.max_range_slider.set_val(cmax)
        if self.new_lim_cb is not None:
            self.new_lim_cb(self.curr_lim)


class ColorKeyInterface(QtWidgets.QWidget):
    """
    Widget that provides a way to select the color of a label.
    """

    def __init__(
        self,
        parent=None,  # type: Optional[Any]
        color_cb=None,  # type: Optional[Callable[str, QtGui.QColor]]
    ):
        # type: (...) -> None
        """
        * color_cb(label, color) - callback to call when color is changed.
        """
        super(ColorKeyInterface, self).__init__(parent)
        self.parent = parent
        self.color_cb = color_cb

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        self.labels = []  # type: List[str]
        self.textlabels = {}  # type: Dict[str, QtGui.QColor]
        self.colorbuttons = {}  # type: Dict[str, QtWidgets.QPushButton]
        self.row_hboxes = {}  # type: Dict[str, QtWidgets.QHBoxLayout]

    def on_color_button_clicked(self, label):
        # type: (str) -> None
        # Pop up color dialog
        # if color not none, change button color AND call self.color_cb(color)
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            print("User requested %s" % (color.name()))
            self.colorbuttons[label].setStyleSheet(
                "QPushButton {background-color: %s}" % (color.name())
            )
            self.color_cb(label, str(color.name()))

    def add_row(self, label, color):
        # type: (str, QtGui.QColor) -> None
        """
        The label here will be used when calling color_cb.
        """
        self.labels.append(label)
        self.colorbuttons[label] = QtWidgets.QPushButton("")
        self.colorbuttons[label].clicked.connect(
            lambda: self.on_color_button_clicked(label),
        )
        self.colorbuttons[label].setStyleSheet(
            "QPushButton {background-color: %r}" % (color)
        )
        self.colorbuttons[label].setFixedSize(20, 20)

        self.textlabels[label] = QtWidgets.QLabel(label)

        self.row_hboxes[label] = QtWidgets.QHBoxLayout()
        self.row_hboxes[label].addWidget(self.colorbuttons[label])
        self.row_hboxes[label].addWidget(self.textlabels[label])
        self.layout.addLayout(self.row_hboxes[label])

    def remove_row(self, label):
        # type: (str) -> None
        self.labels.remove(label)
        self.layout.removeItem(self.row_hboxes[label])
        self.textlabels[label].deleteLater()
        del self.textlabels[label]
        self.colorbuttons[label].deleteLater()
        del self.colorbuttons[label]


class TextColorInterface(QtWidgets.QWidget):
    """
    Widget that provides:
    a label, two text entry boxes, a color selector, and a button
    for each row added.
    """

    def __init__(
        self,
        parent=None,  # type: Optional[Any]
        color_cb=None,  # type: Optional[Callable[str, QtGui.QColor]]
        params_cb=None,  # type: Optional[Callable[str, Tuple[float, float, str]]]
        remove_cb=None,  # type: Optional[Callable[str]]
    ):
        # type: (...) -> None
        """
        * color_cb(label, color)
        * params_cb(label, params), where params is (float, float, str)
        * remove_cb(label)
        """
        # TODO: I'm not sure what this is needed for?
        super(TextColorInterface, self).__init__(parent)
        self.parent = parent

        self.color_cb = color_cb
        self.params_cb = params_cb
        self.remove_cb = remove_cb

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        self.labels = []  # type: List[str]
        self.text_labels = {}  # type: Dict[str, QtWidgets.QLabel]
        # self.spinboxes = {}
        self.first_textboxes = {}  # type: Dict[str, QtWidgets.QLineEdit]
        self.second_textboxes = {}  # type: Dict[str, QtWidgets.QLineEdit]
        self.color_buttons = {}  # type: Dict[str, QtWidgets.QPushButton]
        self.colors = {}  # type: Dict[str, QtWidgets.QColor]
        self.val1 = {}  # type: Dict[str, float]
        self.val2 = {}  # type: Dict[str, float]
        self.remove_buttons = {}  # type: Dict[str, QtWidgets.QPushButton]
        self.row_hboxes = {}  # type: Dict[str, QtWidgets.QHBoxLayout]

    def _on_color_button_clicked(self, label):
        # type: (str) -> None
        # Pop up color dialog
        # if color not none, change button color AND call self.color_cb(color)
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            stylestr = "QPushButton {background-color: %s}" % (color.name())
            self.color_buttons[label].setStyleSheet(stylestr)
            self.colors[label] = str(color.name())
            if self.color_cb is not None:
                self.color_cb(label, str(color.name()))

    def _on_remove_button_clicked(self, label):
        # type: (str) -> None
        self.remove_row(label)
        if self.remove_cb is not None:
            self.remove_cb(label)

    def _on_textbox_edited(self, textbox, label):
        # type: (int, str) -> None
        try:
            val1 = float(self.first_textboxes[label].text())
            self.val1[label] = val1
        except:
            msg = "unable to cast textbox to float!"
            show_error_message_box(msg)
            self.first_textboxes[label].setText(str(self.val1[label]))
            return
        try:
            val2 = float(self.second_textboxes[label].text())
            self.val2[label] = val2
        except:
            msg = "unable to cast textbox to float!"
            show_error_message_box(msg)
            self.first_textboxes[label].setText(str(self.val2[label]))
            return

        params = (self.val1[label], self.val2[label], self.colors[label])
        if self.params_cb is not None:
            self.params_cb(label, params)

    def _on_spinbox_changed(self, label):
        # type: (str) -> None
        print(
            "spinbox for data %s changed to %f" % (label, self.spinboxes[label].value())
        )

    def add_row(self, label, box1_val, box2_val, color):
        # type: (str, float, float, QtGui.QColor) -> None
        self.labels.append(label)
        self.val1[label] = box1_val
        self.val2[label] = box2_val
        self.colors[label] = color

        self.text_labels[label] = QtWidgets.QLabel(label)

        # I couldn't figure out how to attach to the valueChanged signal,
        # so for now, I'm just going to stick with the text-only entry method.
        # self.spinboxes[label] = QtWidgets.QDoubleSpinBox()
        # self.spinboxes[label].setMinimum(0.0)
        # self.spinboxes[label].setMaximum(1.0)
        # self.spinboxes[label].setSingleStep(0.05)
        # #self.spinboxes[label].valueChanged().connect(lambda: self._on_spinbox_changed(label))
        # self.connect(self.spinboxes[label],
        #              #QtCore.SIGNAL('QtWidgets.QDoubleSpinBox.valueChanged()'),
        #              QtCore.SIGNAL('valueChanged(int)'),
        #              lambda: self._on_spinbox_changed(label))

        self.first_textboxes[label] = QtWidgets.QLineEdit()
        self.first_textboxes[label].setMaximumWidth(60)
        self.first_textboxes[label].setMaximumWidth(70)
        self.first_textboxes[label].setText(str(box1_val))
        self.first_textboxes[label].editingFinished.connect(
            lambda: self._on_textbox_edited(1, label),
        )

        self.second_textboxes[label] = QtWidgets.QLineEdit()
        self.second_textboxes[label].setMaximumWidth(60)
        self.second_textboxes[label].setMaximumWidth(70)
        self.second_textboxes[label].setText(str(box2_val))
        self.second_textboxes[label].editingFinished.connect(
            lambda: self._on_textbox_edited(2, label),
        )

        self.color_buttons[label] = QtWidgets.QPushButton("")
        self.color_buttons[label].clicked.connect(
            lambda: self._on_color_button_clicked(label),
        )
        self.color_buttons[label].setStyleSheet(
            "QPushButton {background-color: %r}" % (color)
        )
        self.color_buttons[label].setFixedSize(20, 20)

        self.remove_buttons[label] = QtWidgets.QPushButton("remove")
        self.remove_buttons[label].clicked.connect(
            lambda: self._on_remove_button_clicked(label),
        )

        self.row_hboxes[label] = QtWidgets.QHBoxLayout()
        self.row_hboxes[label].addWidget(self.color_buttons[label])
        self.row_hboxes[label].addWidget(self.text_labels[label])
        self.row_hboxes[label].addStretch(1)
        self.row_hboxes[label].addWidget(self.first_textboxes[label])
        # self.row_hboxes[label].addWidget(self.spinboxes[label])
        self.row_hboxes[label].addWidget(self.second_textboxes[label])
        self.row_hboxes[label].addWidget(self.remove_buttons[label])

        self.layout.addLayout(self.row_hboxes[label])

    def remove_row(self, label):
        # type: (str) -> None
        self.labels.remove(label)
        self.layout.removeItem(self.row_hboxes[label])

        for elem in [
            self.color_buttons,
            self.text_labels,
            self.first_textboxes,
            self.second_textboxes,
            self.remove_buttons,
        ]:
            elem[label].deleteLater()
            del elem[label]


class RadioCheckInterface(QtWidgets.QWidget):
    """
    Widget that provides a set of radio buttons and check boxes for the
    same list of labels. Useful for editing picks, where we want to control
    the visibility of multiple maxima, but only be actively editing one
    pick file at a time.
    """

    def __init__(
        self,
        parent=None,  # type: Optional[Any]
        radio_cb=None,  # type: Optional[Callable[str]]
        check_cb=None,  # type: Optional[Callable[str, bool]]
        color_cb=None,  # type: Optional[Callable[str, any]]
    ):
        # type: (...) -> None
        """
        * radio_cb(string) - callback to call when any radio button clicked.
          (if one is selected, others are all unclicked).
          Arg is the button's label.
        * check_cb(string, bool) - callback for whenever a checkbox changes
          state. Args are the box's label, and it's resulting state.
        * color_cb(string, color) - callback for setting a pick line to a
          different color
        """
        super(RadioCheckInterface, self).__init__(parent)
        self.parent = parent
        self.radio_cb = radio_cb
        self.check_cb = check_cb
        self.color_cb = color_cb

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        # After grouping by rows, the title no longer aligned.
        # self.radiobutton_label = QtWidgets.QLabel('active')
        # self.checkbox_label = QtWidgets.QLabel('show')
        # self.textlabel_label = QtWidgets.QLabel('pick file')
        # self.colorbutton_label = QtWidgets.QLabel('color')

        # self.title_hbox = QtWidgets.QHBoxLayout()
        # self.title_hbox.addWidget(self.radiobutton_label)
        # self.title_hbox.addWidget(self.checkbox_label)
        # self.title_hbox.addStretch(1)
        # self.title_hbox.addWidget(self.textlabel_label)
        # self.title_hbox.addWidget(self.colorbutton_label)

        # self.layout.addLayout(self.title_hbox)

        self.row_hboxes = {}  # type: Dict[str, QtWidgets.QHBoxLayout]
        self.checkboxes = {}  # type: Dict[str, QtWidgets.QCheckBox]
        self.radiobuttons = {}  # type: Dict[str, QtWidgets.QRadioButton]
        self.textlabels = {}  # type: Dict[str, QtWidgets.QLabel]
        self.colorbuttons = {}  # type: Dict[str, QtWidgets.QPushButton]
        # used for looking up colors
        self.colors = {}  # type: Dict[str, QtGui.QColor]

        # When adding buttons to the group, set the id to the label's index
        # in the labels array.
        self.labels = []  # type: List[str]
        self.radio_group = QtWidgets.QButtonGroup()
        self.radio_group.buttonPressed.connect(
            self.on_radio_button_pressed,
        )

        # Same for the checkbox goup, but this is a non-exclusive group.
        self.checkbox_group = QtWidgets.QButtonGroup()
        self.checkbox_group.setExclusive(False)
        self.checkbox_group.buttonPressed.connect(
            self.on_checkbox_pressed,
        )

        # TODO: come up with a better set of default colors?
        # TODO: Generate better initial colors than random ...
        # color = '#%06x' % np.random.randint(0xFFFFFF)
        self.pick_color_gen = itertools.cycle(
            ["green", "red", "blue", "magenta", "cyan", "purple"]
        )

    def get_color(self, label):
        # type: (str) -> QtGui.QColor
        return self.colors[label]

    def add_row(self, label):
        # type: (str) -> None
        self.labels.append(label)

        self.radiobuttons[label] = QtWidgets.QRadioButton("")
        self.radio_group.addButton(self.radiobuttons[label], self.labels.index(label))

        self.checkboxes[label] = QtWidgets.QCheckBox("")
        self.checkbox_group.addButton(self.checkboxes[label], self.labels.index(label))

        self.textlabels[label] = QtWidgets.QLabel(label)

        self.colorbuttons[label] = QtWidgets.QPushButton("")
        self.colorbuttons[label].setFixedSize(20, 20)
        color = self.pick_color_gen.next()
        self.colorbuttons[label].clicked.connect(
            lambda: self.on_color_button_clicked(label),
        )
        self.colorbuttons[label].setStyleSheet(
            "QPushButton {background-color: %s}" % (color)
        )
        self.colors[label] = color

        self.row_hboxes[label] = QtWidgets.QHBoxLayout()
        self.row_hboxes[label].addWidget(self.radiobuttons[label])
        self.row_hboxes[label].addWidget(self.checkboxes[label])
        self.row_hboxes[label].addStretch(1)
        self.row_hboxes[label].addWidget(self.textlabels[label])
        self.row_hboxes[label].addWidget(self.colorbuttons[label])

        self.layout.addLayout(self.row_hboxes[label])

    def on_color_button_clicked(self, label):
        # type: (str) -> None
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            self.colorbuttons[label].setStyleSheet(
                "QPushButton {background-color: %s}" % (color.name())
            )
            if self.color_cb is not None:
                self.color_cb(label, str(color.name()))

    def on_radio_button_pressed(self, button_id):
        # type: (int) -> None
        label = self.labels[button_id]
        if self.radio_cb is not None:
            self.radio_cb(label)

    def on_checkbox_pressed(self, button_id):
        # type: (int) -> None
        label = self.labels[button_id]
        # For some reason, this returns 1 when event causes box to be
        # unchecked, and 0 when it winds up checked.
        checked = self.checkboxes[label].isChecked()
        if self.check_cb is not None:
            self.check_cb(label, not checked)

    def activate_radio_checkbox(self):
        # type: () -> None
        """
        This causes the checkbox of the currently-active radio button to be
        selected. It is needed for programatically showing the max when
        autopick is recalculated.
        """
        for button_idx, button_id in enumerate(self.labels):
            if self.radiobuttons[button_id].isChecked():
                self.checkboxes[button_id].setCheckState(-1)
                self.check_cb(button_id, True)
