import itertools
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib
import numpy as np
import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .plotUtilities import show_error_message_box


# TODO(lindzey): Using a QSlider for this isn't great now that we're
#  also supporting floats (BAS provides intensity data as float, not int)
#  The QSliders are int-only, so can only be dragged in integral increments.
#  So, if you want more resolution, have to type in the textbox, which does work.
class DoubleSlider(QtWidgets.QWidget):
    """
    Widget that provides two sliders as a way to update the integer min/max
    value for a range.
    * Does not force textbox values to be within the range of the bar.
    NB - does force minval <= maxval
    TODO: Would be nicer if it was a single slider flanked by text boxes,
    but I didn't immediately see how to do that.
    """

    def __init__(
        self,
        parent: Optional[Any] = None,
        new_lim_cb=None,
        curr_lim: Tuple[float, float] = (0.0, 1.0),
    ):
        """
        * new_lim_cb([min,max]) - callback to call whenever either side
          of the limit changes.
        """
        super(DoubleSlider, self).__init__(parent)
        self.parent = parent
        self.new_lim_cb = new_lim_cb

        self.curr_lim = curr_lim

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        # TODO - have sliders only call update when _released_,
        # otherwise it may try to redraw the image tons.
        self.slider_set_min_label = QtWidgets.QLabel("MIN")
        self.slider_set_max_label = QtWidgets.QLabel("MAX")

        # Try putting this before creating the RangeSlider
        self.min_slider_textbox = QtWidgets.QLineEdit()
        self.min_slider_textbox.setMinimumWidth(90)
        self.min_slider_textbox.setMaximumWidth(120)
        self.min_slider_textbox.setText(f"{self.curr_lim[0]}")
        self.min_slider_textbox.editingFinished.connect(
            self._on_min_slider_textbox_edited,
        )




        self.slider_fig = Figure((1, 1))
        self.slider_canvas = FigureCanvas(self.slider_fig)
        self.slider_canvas.setParent(self)

        # Can't use full xlim because the slider handles will go off the sides
        self.slider_ax = self.slider_fig.add_axes([0.03, 0, 0.94, 1])

        # Want the canvas + figure to blend in with Qt Widget, rather
        # than standing out with a white background
        palette = QtGui.QGuiApplication.palette()
        qt_color = palette.window().color()
        mpl_color = [qt_color.redF(), qt_color.greenF(), qt_color.blueF(), qt_color.alphaF()]
        self.slider_ax.patch.set_facecolor(mpl_color)  # not necessary
        self.slider_fig.patch.set_facecolor(mpl_color)  # This is what did it

        slider_label = None
        self.range_slider = matplotlib.widgets.RangeSlider(
            self.slider_ax, slider_label, curr_lim[0], curr_lim[1], valfmt=None
        )
        # TODO: Figure out how to get on_changed to only fire on mouse
        # release event, rather than updating it constantly while dragging.
        self.range_slider.on_changed(self._on_range_slider_changed)
        # This works, but then the highlighted region is too tall.
        # I also don't like reaching into the class to change attributes like this
        # self.range_slider.track.set_height(0.25)
        print("line 91")

        self.slider_canvas.setFixedHeight(15)
        # TODO: Set horizontal policy to be Expanding
        # The below doesn't work because the canvas isn't a widget.
        # self.slider_canvas.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
        # TODO: Set horizontal hint to be smaller
        self.slider_widget = QtWidgets.QWidget()
        self.slider_layout = QtWidgets.QHBoxLayout()
        self.slider_layout.addWidget(self.slider_canvas)
        self.slider_widget.setLayout(self.slider_layout)
        self.slider_widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        print("line 103")
        self.slider_min_label = QtWidgets.QLabel(f"{self.curr_lim[0]:.2f}")
        self.slider_max_label = QtWidgets.QLabel(f"{self.curr_lim[1]:.2f}")
        self.slider_hbox = QtWidgets.QHBoxLayout()
        self.slider_hbox.addWidget(self.slider_min_label)
        # self.slider_hbox.addWidget(self.slider_canvas)
        self.slider_hbox.addStretch(1.0)
        #self.slider_hbox.addWidget(self.slider_widget)
        self.slider_hbox.addWidget(self.slider_max_label)

        print("line 113")

        """
        self.min_slider_label2 = QtWidgets.QLabel(f"{self.curr_lim[0]:.1f}")
        self.min_slider_label3 = QtWidgets.QLabel(f"{self.curr_lim[1]:.1f}")
        self.min_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.min_slider.setRange(self.curr_lim[0], self.curr_lim[1])
        self.min_slider.setValue(self.curr_lim[0])
        self.min_slider.setTracking(False)
        self.min_slider.valueChanged.connect(
            self._on_min_slider_changed,
        )
        """


        set_min_slider_hbox = QtWidgets.QHBoxLayout()
        set_min_slider_hbox.addWidget(self.slider_set_min_label)
        set_min_slider_hbox.addStretch(1)
        set_min_slider_hbox.addWidget(self.min_slider_textbox)
        """
        min_slider_lower_hbox = QtWidgets.QHBoxLayout()
        min_slider_lower_hbox.addWidget(self.min_slider_label2)
        min_slider_lower_hbox.addWidget(self.min_slider)
        min_slider_lower_hbox.addWidget(self.min_slider_label3)
        """

        """
        # And now for the max-bounds slider ...
        self.max_slider_label1 = QtWidgets.QLabel("MAX")
        self.max_slider_label2 = QtWidgets.QLabel(f"{self.curr_lim[0]:.1f}")
        self.max_slider_label3 = QtWidgets.QLabel(f"{self.curr_lim[1]:.1f}")
        self.max_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.max_slider.setRange(self.curr_lim[0], self.curr_lim[1])
        self.max_slider.setValue(self.curr_lim[1])
        # Don't continually call valueChanged
        self.max_slider.setTracking(False)
        self.max_slider.valueChanged.connect(
            self._on_max_slider_changed,
        )
        """

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
        """
        max_slider_lower_hbox = QtWidgets.QHBoxLayout()
        max_slider_lower_hbox.addWidget(self.max_slider_label2)
        max_slider_lower_hbox.addWidget(self.max_slider)
        max_slider_lower_hbox.addWidget(self.max_slider_label3)
        """

        self.layout.addLayout(set_min_slider_hbox)
        self.layout.addLayout(set_max_slider_hbox)
        # self.layout.addLayout(min_slider_lower_hbox)
        self.layout.addWidget(self.slider_widget)
        self.layout.addLayout(self.slider_hbox)
        # self.layout.addLayout(max_slider_lower_hbox)

        print("line 172")

    # TODO: It would be nice to have this as a decorator, rather
    # than calling both independently, but that got complicated ...
    def disconnect_callbacks(self) -> None:
        """
        Disables all callbacks associated with updating the sliders and
        textboxes. Does NOT disable the new_lim_cb
        (which really would be setting it to None).
        """
        self.min_slider_textbox.editingFinished.disconnect(
            self._on_min_slider_textbox_edited,
            )
        self.max_slider_textbox.editingFinished.disconnect(
            self._on_max_slider_textbox_edited,
        )
        """
        self.min_slider.valueChanged.disconnect(
            self._on_min_slider_changed,
        )
        self.max_slider.valueChanged.disconnect(
            self._on_max_slider_changed,
        )
        """
        # Hacky way to disconnect this callback
        # This DOES NOT WORK. It seems to just add callbacks,
        # rather than reset it
        #self.range_slider.on_changed(lambda x: None)

    def reconnect_callbacks(self) -> None:
        self.min_slider_textbox.editingFinished.connect(
            self._on_min_slider_textbox_edited,
        )
        self.max_slider_textbox.editingFinished.connect(
            self._on_max_slider_textbox_edited,
        )
        """
        self.min_slider.valueChanged.connect(
            self._on_min_slider_changed,
        )
        self.max_slider.valueChanged.connect(
            self._on_max_slider_changed,
        )
        """
        # self.range_slider.on_changed(self._on_range_slider_changed)

    def set_range(self, lim: Tuple[float, float]) -> None:
        """
        Resetting the range of the slider automatically sets it to
        be at the full range.
        Does not trigger any callbacks.
        """
        print(f"Calling set_range: {lim}")
        rmin, rmax = lim
        self.disconnect_callbacks()
        """
        self.max_slider.setRange(rmin, rmax)
        self.max_slider_label2.setText(f"{rmin:.1f}")
        self.max_slider_label3.setText(f"{rmax:.1f}")
        self.min_slider.setRange(rmin, rmax)
        self.min_slider_label2.setText(f"{rmin:.1f}")
        self.min_slider_label3.setText(f"{rmax:.1f}")
        """
        # Need to reconnect before calling range_slider's methods
        # because those will trigger the same callback that user changes
        # would, and that disconnects calbacks.
        self.reconnect_callbacks()
        # THis is a bit hacky; setting max first because the default
        # max values are smaller than the new min is likely to be
        # Need to set these in an order that's guaranteed to be valid.
        # If max greater than current min, we can set it.
        # Otherwise, need to update the minimum first.
        print(f"Before setting, range_slider's range = {self.range_slider.valmin}, {self.range_slider.valmax}")
        print(f"Before setting, range_slider's values = {self.range_slider.val}")
        # Directly changing valmin/valmax because the widget didn't provide an API call
        # OH! It would probably be better to just create a new slider
        # and discard the existing one.
        """
        self.range_slider.valmin = rmin
        self.range_slider.valmax = rmax
        self.range_slider.set_val(lim)
        """
        slider_label = None
        self.range_slider = matplotlib.widgets.RangeSlider(
            self.slider_ax, slider_label, lim[0], lim[1], valinit=lim, valfmt=None
        )
        self.slider_min_label.setText(f"{rmin:.2f}")
        self.slider_max_label.setText(f"{rmax:.2f}")
        self.range_slider.on_changed(self._on_range_slider_changed)
        print(f"After setting, range_slider's range = {self.range_slider.valmin}, {self.range_slider.valmax}")
        print(f"After setting, range_slider's values = {self.range_slider.val}")
        """
        if rmax > self.curr_lim[0]:
            self.range_slider.set_max(rmax)
            self.range_slider.set_min(rmin)
        else:
            self.range_slider.set_min(rmin)
            self.range_slider.set_max(rmax)
        """
        self.set_value(lim)

    def set_value(self, lim: Tuple[float, float]) -> None:
        """
        Updates the slider values, w/o changing their range.
        Does not trigger callbacks.
        """
        self.curr_lim = lim
        rmin, rmax = lim
        self.disconnect_callbacks()
        # self.max_slider.setValue(rmax)
        self.max_slider_textbox.setText(f"{rmax:.2f}")
        # self.min_slider.setValue(rmin)
        self.min_slider_textbox.setText(f"{rmin:.2f}")
        self.reconnect_callbacks()

    # def _on_min_slider_changed(self) -> None:
    #     input_min = self.min_slider.value()
    #     self.update_min_value(input_min)

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
        self.disconnect_callbacks()
        # self.min_slider.setValue(cmin)
        self.min_slider_textbox.setText(f"{cmin:.2f}")
        self.curr_lim = (cmin, self.curr_lim[1])
        self.range_slider.set_val(self.curr_lim)
        self.reconnect_callbacks()
        if self.new_lim_cb is not None:
            self.new_lim_cb(self.curr_lim)

    # def _on_max_slider_changed(self) -> None:
    #     input_max = self.max_slider.value()
    #     self.update_max_value(input_max)

    def _on_range_slider_changed(self, newlim) -> None:
        # TODO: Somehow, this is called MANY times whenever the
        #  textbox is changed.
        print(f"Called _on_range_slider_changed with newlim = {newlim}")
        self.disconnect_callbacks()
        self.min_slider_textbox.setText(f"{newlim[0]:.2f}")
        self.max_slider_textbox.setText(f"{newlim[1]:.2f}")
        self.reconnect_callbacks()
        self.curr_lim = newlim
        if self.new_lim_cb is not None:
            self.new_lim_cb(newlim)

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
        self.disconnect_callbacks()
        # self.max_slider.setValue(cmax)
        self.max_slider_textbox.setText(f"{cmax:.2f}")
        self.curr_lim = (self.curr_lim[0], cmax)
        self.range_slider.set_val(self.curr_lim)
        self.reconnect_callbacks()
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
            plotUtilities.show_error_message_box(msg)
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
