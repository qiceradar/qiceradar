# Copyright 2022-2025 Laura Lindzey, UW-APL
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


"""
Standalone viewer for UTIG's radar data; heavily inspired by
(x)eva(s)'s UI. However, in addition to keeping the same picking controls and
picker, enables switching between data products.

Also used as part of deva, for displaying radar data in context with the map.

# For now, this needs to be run from an environment set up for QGIS.
# I really need to sort out python environments on my machine.

OLD_PATH=$PATH
OLD_PYTHONPATH=$PYTHONPATH

QGIS_VERSION="QGIS-LTR"

export PATH=/Applications/$QGIS_VERSION.app/Contents/MacOS/bin:$PATH
export PYTHONPATH=/Applications/$QGIS_VERSION.app/Contents/Resources/python/:/Applications/$QGIS_VERSION.app/Contents/Resources/python/plugins
export QGIS_PREFIX_PATH=/Applications/$QGIS_VERSION.app/Contents/MacOS
export QT_QPA_PLATFORM_PLUGIN_PATH=/Applications/$QGIS_VERSION.app/Contents/PlugIns/platforms/
export DYLD_INSERT_LIBRARIES=/Applications/$QGIS_VERSION.app/Contents/MacOS/lib/libsqlite3.dylib
"""

import pathlib
from typing import Callable, Dict, List, Optional, Tuple

import matplotlib as mpl
import matplotlib.backend_bases
import numpy as np
from matplotlib.backend_bases import MouseButton

mpl.use("Qt5Agg")
import matplotlib.widgets as mpw
import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

# I'm not sure I like this -- would prefer being able to run the viewer standalone, like radarFigure is currently used.
# Look into better options for logging messages?
from qgis.core import QgsMessageLog

# import radutils.radutils as radutils
from .datautils import db_utils, radar_utils
from .plotutils import scalebar, sparkline, xevas
from .plotutils.matplotlib_utils import (
    SaveToolbar,
    get_ax_shape,
)
from .plotutils.pyqt_utils import HLine
from .radar_viewer_widgets import DoubleSlider, ScalebarControls

# TODO: These need to be renamed. it's currently really confusing ...
# * mplUtilites - things that depend only on matplotlib
# * radarWidgets - currently are really pyqt widgets
# * plotUtilites - other pyqt stuff that doesn't count as widgets


# Notes on organization:
# * There's a hierarchy of functions that actually update the screen:
#   1) full_redraw() - this is for when the radar background has changed.
#      This will be cmap/clim changes, or xlim/ylim, or chan/product.
#   2) data_blit() - whenever any of the usually static data has changed.
#      This includes picks, pick maxima, and the various analysis/ELSA
#      plots.
#   3) cursor_blit() - for anything that follows the mouse around.
#      needs to be fast =)
#      This is currently just the trace, crosshairs & camera.
#
#   I'm not entirely sold that it's better to do it this way, rather than
#   re-capture the background/blit for each individual element, but it's
#   enough of a speed improvement, and seemed simpler. Maybe later I can break
#   it down (was going to be complicated since I couldn't figure out how to
#   use the sparkline as an artist)
#
# * The only functions that call draw_artist are data_blit, cursor_blit, and
#   the plot_*() functions that are called by data_blit.
# * Only *_set_visible should call artist.set_visible() ... any other calls
#   are superfluous, since blitting requires setting invisible/visible, and
#   if it has been modified, the correct blitting function has to be called
#   anyway to actually draw it.


# TODO(lindzey): I don't love how this mixes dataset-specific products/channels
#     with data-independent colormaps.
class PlotConfig:
    """
    Various constants about the plot configuration, that won't be
    changed at runtime.
    """

    def __init__(self, available_products: List[str]) -> None:
        # TODO(lindzey): Clean this up. shouldn't need to have this in multiple places.
        self.all_products = available_products
        self.all_cmaps = ["gray", "jet", "viridis", "inferno", "seismic", "Greys"]
        # Depending on the cmap, we may want to show the spark lines in
        # different colors ...
        self.cmap_major_colors: Dict[str, str] = {}
        self.cmap_minor_colors: Dict[str, str] = {}
        for cmap in ["gray", "Greys"]:
            # I had the rcoeff sparkline as 'c'/'b'
            self.cmap_major_colors[cmap] = "r"
            self.cmap_minor_colors[cmap] = "orange"
        for cmap in ["jet", "viridis", "inferno", "seismic"]:
            self.cmap_major_colors[cmap] = "k"
            self.cmap_minor_colors[cmap] = "grey"


# Hacky way of creating structs to hold all the various data...
# TODO: Should these wind up non-expandable?
class PlotParams:
    """
    All the user-supplied parameters required for regenerating the plot
    (Includes some that depend on the data, if the user has final say.)

    Some are initialized here; I'm not sure if that's a good idea.
    """

    def __init__(self, radar_data: radar_utils.RadarData) -> None:
        self.curr_xlim = (0, radar_data.num_traces - 1)
        self.curr_ylim = (radar_data.num_samples - 1, 0)

        # how many traces are skipped between the displayed traces
        self.radar_skip: Optional[int] = None

        # which trace the camera cursor should currently be on.
        # NB: I don't think this is only the camera anymore -- repurposed for cursor?
        self.displayed_trace_num: Optional[int] = None

        # Whether these positions should be frozen or updated as the mouse moves
        self.crosshair_frozen = False
        self.trace_frozen = False

        # Whether these should be visible ..
        self.crosshair_visible = False
        self.trace_visible = False

        self.vert_scale_visible = False
        self.vert_scale_length_m: float = 500.0  # Units of m
        # Units of axis-fraction
        self.vert_scale_x0 = 0.05
        self.vert_scale_y0 = 0.1
        self.horiz_scale_visible = False
        self.horiz_scale_length_km: float = 10.0  # Units of km
        # units of axis-fraction
        self.horiz_scale_x0 = 0.1
        self.horiz_scale_y0 = 0.05

        self.product = radar_data.available_products[0]

        self.cmap = "gray"
        self.clim = (0, 1)  # what's currently displayed
        self.cmin = 0  # min val from radar
        self.cmax = 1  # max val from radar

        self.mouse_mode = "zoom"
        self.update_clim_from_radar(radar_data)

    def update_clim_from_radar(self, radar_data: radar_utils.RadarData) -> None:
        """
        Called to update the plotting parameters without changing the bounds.
        """
        self.cmin = radar_data.min_val
        self.cmax = radar_data.max_val

        if self.product == "der":
            init_clim = (-5000, 5000)
        elif self.product == "under":
            init_clim = (0, 1000000)
        else:
            init_clim = (self.cmin, self.cmax)
        self.clim = init_clim


class PlotObjects:
    """
    Various handles that result from plotting that we want to keep in scope.
    Used when updating the plots ...
    This has slots for ALL of them, but some of the RadarWindow classes don't
    use all.
    """

    def __init__(self) -> None:
        # TODO: I'm not sure how to handle this in mypy. I want to use this
        # class like a struct to just pass around the various variables, but
        # all of 'em need to be instantiated at setup time.
        # I wasn't sure how to do a dynamic container class, so I'm just
        # declaring all of 'em here.
        # I'm also not sure how many of 'em need to be kept around vs.
        # just creating them...
        # TODO(lindzey): I don't think that organizing them into a struct
        #  like this buys any clarity.

        # All of these are initialized by create_layout
        self.main_frame: Optional[QtWidgets.QWidget] = None
        self.cursor: Optional[QtGui.QCursor] = None

        self.fig: Optional[Figure] = None
        self.canvas: Optional[FigureCanvas] = None
        self.mpl_toolbar: Optional[SaveToolbar] = None
        self.radar_plot: Optional[mpl.image.AxesImage] = None

        self.dpi: Optional[int] = None

        self.full_ax: Optional[mpl.axes.Axes] = None
        self.radar_ax: Optional[mpl.axes.Axes] = None
        self.xevas_horiz_ax: Optional[mpl.axes.Axes] = None
        self.xevas_vert_ax: Optional[mpl.axes.Axes] = None
        self.pick_ax: Optional[mpl.axes.Axes] = None

        self.xevas_horiz: Optional[xevas.XevasHorizSelector] = None
        self.xevas_vert: Optional[xevas.XevasVertSelector] = None

        self.crosshair_x: Optional[mpl.lines.Line2D] = None
        self.crosshair_y: Optional[mpl.lines.Line2D] = None

        self.trace_sparkline: Optional[sparkline.Sparkline] = None
        self.trace_base: Optional[mpl.lines.Line2D] = None

        self.left_click_rs: Dict[str, mpw.RectangleSelector] = {}
        self.right_click_rs: Dict[str, mpw.RectangleSelector] = {}
        self.mouse_mode_buttons: Dict[str, QtWidgets.QRadioButton] = {}
        self.mouse_mode_group: Optional[QtWidgets.QButtonGroup] = None
        self.citation_button: Optional[QtWidgets.QPushButton] = None
        self.prev_button: Optional[QtWidgets.QPushButton] = None
        self.full_button: Optional[QtWidgets.QPushButton] = None
        self.next_button: Optional[QtWidgets.QPushButton] = None

        self.colormap_buttons: Dict[str, QtWidgets.QRadioButton] = {}
        self.colormap_group: Optional[QtWidgets.QButtonGroup] = None

        self.product_buttons: Dict[str, QtWidgets.QRadioButton] = {}
        self.product_group: Optional[QtWidgets.QButtonGroup] = None

        # We actually want to keep references to these because we check their state
        self.trace_checkbox: Optional[QtWidgets.QCheckBox] = None
        self.crosshair_checkbox: Optional[QtWidgets.QCheckBox] = None

        self.clim_slider: Optional[DoubleSlider] = None

        self.vert_scale_checkbox: Optional[QtWidgets.QCheckBox] = None
        self.vert_scale_length_label: Optional[QtWidgets.QLabel] = None
        self.vert_scale_length_textbox: Optional[QtWidgets.QLineEdit] = None
        self.vert_scale_origin_label: Optional[QtWidgets.QLabel] = None
        self.vert_scale_x0_textbox: Optional[QtWidgets.QLineEdit] = None
        self.vert_scale_y0_textbox: Optional[QtWidgets.QLineEdit] = None

        self.horiz_scale_checkbox: Optional[QtWidgets.QCheckBox] = None
        self.horiz_scale_length_label: Optional[QtWidgets.QLabel] = None
        self.horiz_scale_length_textbox: Optional[QtWidgets.QLineEdit] = None
        self.horiz_scale_origin_label: Optional[QtWidgets.QLabel] = None
        self.horiz_scale_x0_textbox: Optional[QtWidgets.QLineEdit] = None
        self.horiz_scale_y0_textbox: Optional[QtWidgets.QLineEdit] = None

        self.vert_scale: Optional[scalebar.Scalebar] = None
        self.horiz_scale: Optional[scalebar.Scalebar] = None

        self.quit_button: Optional[QtWidgets.QPushButton] = None

        self.cursor_label: Optional[QtWidgets.QLabel] = None
        self.cursor_format: Optional[str] = None


def calc_radar_skip(fig: Figure, ax: mpl.axes.Axes, xlim: Tuple[int, int]) -> int:
    """
    calculates how many traces can be dropped and still have as many
    traces as available pixels.

    Uses curr_xlim so we can re-calculate skip before plotting.
    """
    if xlim is None:
        print("WARNING: called calc_radar_skip w/ xlim==None")
        return 1  # I added this to make mypy happy.
    ax_width, _ = get_ax_shape(fig, ax)
    num_fig_traces = xlim[1] - xlim[0]
    radar_skip = max(1, int(np.ceil(num_fig_traces / ax_width)))
    return radar_skip


class RadarWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        filepath: pathlib.Path,  # Fully-specified path
        db_granule: db_utils.DatabaseGranule,
        db_campaign: db_utils.DatabaseCampaign,
        parent_xlim_changed_cb: Optional[
            Callable[[List[Tuple[float, float]]], None]
        ] = None,
        parent_cursor_cb: Optional[Callable[[float, float], None]] = None,
        close_cb: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        params:
        * filepath - direct path to the file to load
        TODO: should transect be granule?
        * transect -- name of transect
        * database_file -- name of file
        * parent_xlim_changed_cb - callback (e.g. into main QGIS plugin) that keeps
          the highlighted segment of the PST updated. expects a tuple of posix
          times.
        * parent_cursor_cb - callback (e.g. into main QGIS plugin) that puts a mark
          on the map corresponding to where the cursor is in the radarFigure.
        * close_cb - callback for when radar figure is being closed, used so
          the main QGIS plugin can clear the related layers.
        """
        # This is for the QtGui stuff
        super(RadarWindow, self).__init__()

        self.press_event: Optional[matplotlib.backend_bases.MouseEvent] = None
        self.release_event: Optional[matplotlib.backend_bases.MouseEvent] = None

        self.pst = db_granule.granule_name
        self.db_granule = db_granule
        self.db_campaign = db_campaign

        self.parent_xlim_changed_cb = parent_xlim_changed_cb
        self.parent_cursor_cb = parent_cursor_cb
        self.close_cb = close_cb

        # This doesn't seem to work? Instead, the title is just the granule
        # self.setWindowTitle(f"{institution}, {campaign}: {granule}")

        # These parameters should be independent of the plotting tool we use
        # TODO: RadarData should probably have a list of data formats that it
        #   supports, mapped to the

        # TODO: Fix this!
        self.radar_data = radar_utils.RadarData(self.db_granule, filepath)
        self.plot_config = PlotConfig(self.radar_data.available_products)
        self.plot_params = PlotParams(self.radar_data)

        # Set up the visual display, and hook up all the callbacks.
        # TODO: get rid of dependence on plot_params.available_products?
        self.plot_objects = self.create_layout(self.plot_params, self.plot_config)

        # This needs to come after initialize_from_radar, b/c it depends on xlim
        self.initialize_gui_from_params_data(self.plot_params, self.plot_config)

        # This is annoying, because it depends on and modifies plot_params
        # However, I think that all that matters is that the fig and ax exist,
        # not their state.
        assert self.plot_objects.fig is not None
        assert self.plot_objects.radar_ax is not None
        self.plot_params.radar_skip = calc_radar_skip(
            self.plot_objects.fig,
            self.plot_objects.radar_ax,
            self.plot_params.curr_xlim,
        )

        self.plot_objects.radar_plot = self.plot_objects.radar_ax.imshow(
            self.radar_data.data[:, :: self.plot_params.radar_skip].T,
            aspect="auto",
            interpolation="nearest",
            zorder=0,
        )

        # a simple canvas.draw() doesn't work here for some reason...
        # plot
        self.full_redraw()

    # This is hooked up automagically!
    # However, it only works if the focus is on the frame, not the canvas.
    # So, I made the canvas unfocusable...
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if type(event) is QtGui.QKeyEvent:
            self._on_qt_key_press(event)
            # By doing this here, we don't let anybody downstream of this
            # catch 'em. If I wanted to allow that, move event.accept()
            # into the callback so we only accept keypresses that it handles.
            event.accept()
        else:
            event.ignore()

    def initialize_gui_from_params_data(
        self, plot_params: PlotParams, plot_config: PlotConfig
    ) -> None:
        """
        This just sets the current state of various GUI widgets based on:
        * plot params - initial state of buttons
        """
        assert self.plot_objects.radar_ax is not None
        assert self.plot_objects.clim_slider is not None

        # TODO(lindzey): Shouldn't need this input list if we only
        #  create the appropriate buttons given the dataset.
        # for product in plot_config.all_products:
        #     self.plot_objects.product_buttons[product].setEnabled(True)

        # self.plot_objects.product_buttons[plot_params.product].setChecked(True)
        # self.plot_objects.colormap_buttons[plot_params.cmap].setChecked(True)
        self.plot_objects.mouse_mode_buttons[plot_params.mouse_mode].setChecked(True)
        mouse_mode = self.plot_params.mouse_mode
        self.plot_objects.left_click_rs[mouse_mode].set_active(True)
        self.plot_objects.right_click_rs[mouse_mode].set_active(True)

        self.plot_objects.radar_ax.set_xlim(plot_params.curr_xlim)
        self.plot_objects.radar_ax.set_ylim(plot_params.curr_ylim)

        self.plot_objects.clim_slider.set_range((plot_params.cmin, plot_params.cmax))
        self.plot_objects.clim_slider.set_value(plot_params.clim)

    def update_cursor(self, trace_num: int, sample_num: int) -> None:
        """
        Called whenever the mouse moves in the radar viewer's canvas;
        updates info below radargram regarding trace/sample/amplitude/twtt
        corresponding to mouse's current location.
        """
        assert self.plot_objects.cursor_label is not None
        assert self.plot_objects.cursor_format is not None

        db = self.radar_data.data[trace_num, sample_num]
        twtt = self.radar_data.fast_time_us[sample_num]
        self.plot_objects.cursor_label.setText(
            self.plot_objects.cursor_format.format(trace_num, sample_num, db, twtt)
        )

    def maybe_update_trace(self, trace_num: int) -> bool:
        """
        Called if we want to check for frozen before moving the trace.
        """
        if self.plot_params.trace_visible and not self.plot_params.trace_frozen:
            self.update_trace(trace_num)
            return True
        else:
            return False

    def update_trace(self, trace_num: int) -> None:
        """
        Center trace on median, scaled to take up 1/16th of display..
        Raw values are reported in dBm, with a season-dependent offset.
        """
        assert self.plot_objects.trace_sparkline is not None
        assert self.plot_objects.trace_base is not None

        self.plot_params.displayed_trace_num = trace_num

        # TODO: Need to figure out conversion from counts to dB in order to
        # label the trace sparkline. In the meantime, set to 0.
        # TODO(lindzey): consider calculating a reasonable scale + offset
        # from the data itself?
        # offset = radarAnalysis.channel_offsets[self.plot_params.channel]
        # offset = 0
        # trace_dB = self.radar_data.data[trace_num, :] / 1000.0 + offset
        trace_dB = self.radar_data.data[trace_num, :]
        yy = np.arange(0, self.radar_data.num_samples).tolist()

        self.plot_objects.trace_sparkline.set_data(trace_dB, yy, trace_num + 0.5)
        self.plot_objects.trace_base.set_data(
            [trace_num + 0.5, trace_num + 0.5], [0, self.radar_data.num_samples]
        )

    def maybe_update_crosshair(self, trace: int, sample: int) -> bool:
        """
        Called if we want to check for frozen before moving the trace.
        """
        if self.plot_params.crosshair_visible and not self.plot_params.crosshair_frozen:
            self.update_crosshair(trace, sample)
            return True
        else:
            return False

    def update_crosshair(self, trace: int, sample: int) -> None:
        assert self.plot_objects.crosshair_x is not None
        assert self.plot_objects.crosshair_y is not None

        if self.parent_cursor_cb is not None:
            lon = self.radar_data.lon[trace]
            lat = self.radar_data.lat[trace]
            self.parent_cursor_cb(lon, lat)
        else:
            QgsMessageLog.logMessage("update_crosshair: parent_cursor_cb is None")

        self.plot_objects.crosshair_y.set_data(
            [0, self.radar_data.num_traces], [sample, sample]
        )
        self.plot_objects.crosshair_x.set_data(
            [trace, trace], [0, self.radar_data.num_samples]
        )

    # TODO: This is ugly -- mypy doesn't currently pass, so I've wound up
    #   adding type checks + fixes in the code that should be redundant.
    def update_xlim(self, new_xlim: Tuple[int, int]) -> None:
        assert self.plot_objects.fig is not None
        assert self.plot_objects.radar_ax is not None
        assert self.plot_objects.xevas_horiz is not None

        if not isinstance(new_xlim[0], int) or not isinstance(new_xlim[1], int):
            print("update_xlim: expects integers, since we are plotting an image")
            xmin = int(round(new_xlim[0]))
            xmax = int(round(new_xlim[1]))
            new_xlim = [xmin, xmax]
        self.plot_params.curr_xlim = new_xlim
        self.plot_params.radar_skip = calc_radar_skip(
            self.plot_objects.fig, self.plot_objects.radar_ax, new_xlim
        )
        self.plot_objects.radar_ax.set_xlim(new_xlim)
        # It's OK, this isn't infinitely circular ...
        # update_selection doesn't trigger any callbacks.
        num_traces = self.radar_data.num_traces
        self.plot_objects.xevas_horiz.update_selection(
            (
                1.0 * new_xlim[0] / (num_traces - 1),
                1.0 * new_xlim[1] / (num_traces - 1),
            )
        )

    def update_ylim(self, new_ylim: Tuple[int, int]) -> None:
        assert self.plot_objects.radar_ax is not None
        assert self.plot_objects.xevas_vert is not None

        if not isinstance(new_ylim[0], int) or not isinstance(new_ylim[1], int):
            print("update_ylim: expects integers, since we are plotting an image")
            ymin = int(round(new_ylim[0]))
            ymax = int(round(new_ylim[1]))
            new_ylim = [ymin, ymax]
        self.plot_params.curr_ylim = new_ylim
        self.plot_objects.radar_ax.set_ylim(new_ylim)
        # It's OK, this isn't infinitely circular ...
        # update_selection doesn't trigger any cbs.
        num_samples = self.radar_data.num_samples
        self.plot_objects.xevas_vert.update_selection(
            (
                1 - 1.0 * new_ylim[0] / (num_samples - 1),
                1 - 1.0 * new_ylim[1] / (num_samples - 1),
            )
        )

    def full_redraw(self) -> None:
        """
        Does a full redraw of everything; radar_data, transect_data and
        plot_params should have all the information to update plot_objects.
        I expect this to only be necessary if axes, cmap, clim,
        or plot_size changes.

        NB - clim/cmap still requires the full one, b/c I want to capture
          the state w/o any artists.
        * if they're animated=True, then they won't show up after the draw
          w/o a blit, so might as well do a full one anyways.
        * if they're animated=False, then I'll need to clear 'em off
          before recording, which also requires a draw.
        """
        assert self.plot_objects.canvas is not None
        assert self.plot_objects.full_ax is not None
        assert self.plot_objects.radar_plot is not None

        data = self.radar_data.data
        xlim = self.plot_params.curr_xlim
        ylim = self.plot_params.curr_ylim
        radar_skip = self.plot_params.radar_skip
        self.plot_objects.radar_plot.set_data(
            data[xlim[0] : xlim[1] : radar_skip, ylim[1] : ylim[0]].T
        )
        extent = (xlim[0], xlim[1], ylim[0], ylim[1])
        self.plot_objects.radar_plot.set_extent(extent)
        self.plot_objects.radar_plot.set_cmap(self.plot_params.cmap)
        self.plot_objects.radar_plot.set_clim(self.plot_params.clim)

        self.cursor_set_invisible(self.plot_objects)
        self.data_set_invisible(self.plot_objects)

        # Needs to happen before calls to blitting, but after updating
        # other axes. We use full_ax in order to also capture the
        # axis labels and xevas bars
        self.plot_objects.canvas.draw()
        self.radar_restore = self.plot_objects.canvas.copy_from_bbox(
            self.plot_objects.full_ax.bbox
        )

        # QUESTION: Surely these set_visible calls are redundant, since
        # the blitting sets them invisible/visible?
        self.cursor_set_visible(self.plot_objects, self.plot_params)
        self.data_set_visible(self.plot_objects, self.plot_params)

        self.data_blit()  # also calls cursor_blit

        # Initialize the map cursor to something reasonable
        # TODO: This gets called at every redraw, so it resets the
        #   crosshair cursor until the user moves the mouse again.
        if self.parent_cursor_cb is not None:
            lon = self.radar_data.lon[0]
            lat = self.radar_data.lat[0]
            self.parent_cursor_cb(lon, lat)

        if self.parent_xlim_changed_cb is not None:
            xmin, xmax = self.plot_params.curr_xlim
            # TODO: Can probably subsample this.
            points = [
                (self.radar_data.lon[idx], self.radar_data.lat[idx])
                for idx in range(xmin, xmax)
            ]
            self.parent_xlim_changed_cb(points)

    def data_blit(self) -> None:
        """
        This redraws all the various rcoeff/pick/etc plots, but not the
        radar background.
        # TODO: I haven't tested  whether it would be faster to do it like
        # this or do a per-artist blit when it changes. However, this seems
        # easier/cleaner.
        """
        assert self.plot_objects.canvas is not None
        assert self.plot_objects.full_ax is not None

        self.plot_objects.canvas.restore_region(self.radar_restore)

        self.data_set_visible(self.plot_objects, self.plot_params)
        # TODO: If this series starts getting too slow, move the "set_data"
        # logic back to the callbacks that change it. However, there are
        # enough things that change the picks/max values that it's a lot
        # simpler to put all of that right here.

        self.plot_scalebars()

        self.plot_objects.canvas.update()

        self.data_restore = self.plot_objects.canvas.copy_from_bbox(
            self.plot_objects.full_ax.bbox
        )

        self.cursor_blit()

    def cursor_blit(self) -> None:
        """
        Restores JUST the background, not any of the mouse-following
        artists, then redraws all of 'em.

        I'm a little worried about how long it'll take to redraw
        ALL of 'em, but trying to recapture only the bits that
        changed seems combinatorially annoying.
        Plus, the reflection coeff/elsa plots don't need to be blitted.
        """
        assert self.plot_objects.canvas is not None
        assert self.plot_objects.crosshair_x is not None
        assert self.plot_objects.crosshair_y is not None
        assert self.plot_objects.radar_ax is not None
        assert self.plot_objects.trace_base is not None
        assert self.plot_objects.trace_sparkline is not None

        # TODO: Make this more general, rather than hardcoding artists in?
        # I couldn't figure out how to do it alongside the special cases
        # for the sparkline (and making the sparkline an artist ...
        # was a no-go)
        self.plot_objects.canvas.restore_region(self.data_restore)

        self.cursor_set_visible(self.plot_objects, self.plot_params)

        # I tried moving all plotting to a different function and always
        # calling it, but set_data is slow. Much better to only set it when
        # something has changed, and it's easier to do so in a callback.

        # Draw the artists that need to be blitted ...this needs to happen
        # after the restore_region and set_visible and before canvas.update()
        self.plot_objects.radar_ax.draw_artist(self.plot_objects.crosshair_x)
        self.plot_objects.radar_ax.draw_artist(self.plot_objects.crosshair_y)

        self.plot_objects.radar_ax.draw_artist(self.plot_objects.trace_base)
        for element in self.plot_objects.trace_sparkline.elements.values():
            self.plot_objects.radar_ax.draw_artist(element)

        # This is oft-recommended but reputed to leak memory:
        # (http://bastibe.de/2013-05-30-speeding-up-matplotlib.html)
        # self.plot_objects.canvas.blit(self.plot_objects.radar_ax.bbox)
        # This seems to be just about as fast ...
        self.plot_objects.canvas.update()
        # print("time for cursor blit:", time.time() - t0)

    def data_set_invisible(self, plot_objects: PlotObjects) -> None:
        """
        Set ALL overlays invisible.
        """
        assert plot_objects.vert_scale is not None
        assert plot_objects.horiz_scale is not None
        plot_objects.vert_scale.set_visible(False)
        plot_objects.horiz_scale.set_visible(False)

    # TODO(lindzey): It's weird that we need params to set visible, but not for invisible.
    def data_set_visible(
        self, plot_objects: PlotObjects, plot_params: PlotParams
    ) -> None:
        """
        Replot various data overlays based on configuration in plot_params.
        Does NOT turn everything on; only those that are enabled.
        """
        assert plot_objects.vert_scale is not None
        assert plot_objects.horiz_scale is not None
        plot_objects.vert_scale.set_visible(plot_params.vert_scale_visible)
        plot_objects.horiz_scale.set_visible(plot_params.horiz_scale_visible)

    def cursor_set_invisible(self, plot_objects: PlotObjects) -> None:
        assert plot_objects.crosshair_x is not None
        assert plot_objects.crosshair_y is not None
        assert plot_objects.trace_sparkline is not None
        assert plot_objects.trace_base is not None
        plot_objects.crosshair_x.set_visible(False)
        plot_objects.crosshair_y.set_visible(False)
        plot_objects.trace_sparkline.set_visible(False)
        plot_objects.trace_base.set_visible(False)

    def cursor_set_visible(
        self, plot_objects: PlotObjects, plot_params: PlotParams
    ) -> None:
        """
        Restores any elements that follow the mouse around to be visible
        if they were supposed to be ...
        """
        assert plot_objects.crosshair_x is not None
        assert plot_objects.crosshair_y is not None
        assert plot_objects.trace_sparkline is not None
        assert plot_objects.trace_base is not None
        plot_objects.crosshair_x.set_visible(plot_params.crosshair_visible)
        plot_objects.crosshair_y.set_visible(plot_params.crosshair_visible)
        plot_objects.trace_sparkline.set_visible(plot_params.trace_visible)
        plot_objects.trace_base.set_visible(plot_params.trace_visible)

    def radar_from_pick_coords(self, pick: Tuple[float, float]) -> Tuple[int, int]:
        """
        Converts point in display coords (from the pick axis) into data
        coords in the radar_ax. This thresholds to the shape of the radar
        axis, which means that picks just slightly off the side will be
        interpreted as labeling the last trace.
        """
        assert self.plot_objects.radar_ax is not None
        # I tried precalculating this, but it was awkward to make sure it got
        # initialized correctly. It takes < 0.2ms per call, so I'm OK with
        # that penalty. Putting it in initialize_gui_from_params_data just
        # after set_{xlim,ylim} didn't do it.
        inv = self.plot_objects.radar_ax.transData.inverted()
        # p0 = inv.transform(pick)
        px, py = inv.transform(pick)
        xlim = self.plot_params.curr_xlim
        ylim = self.plot_params.curr_ylim
        # xx = min(xlim[1], max(xlim[0], int(round(p0[0]))))
        xx = min(xlim[1], max(xlim[0], int(round(px))))
        # Tricksy .. axis reversed!
        # yy = max(ylim[1], min(ylim[0], int(round(p0[1]))))
        yy = max(ylim[1], min(ylim[0], int(round(py))))
        return xx, yy

    def _on_left_rect_click_zoom(
        self,
        eclick: matplotlib.backend_bases.MouseEvent,
        erelease: matplotlib.backend_bases.MouseEvent,
    ) -> None:
        """left click-and-drag zooms in."""
        num_traces = self.radar_data.num_traces
        num_samples = self.radar_data.num_samples
        click = self.radar_from_pick_coords((eclick.x, eclick.y))
        release = self.radar_from_pick_coords((erelease.x, erelease.y))
        x0 = min(max(0, click[0]), max(0, release[0]))
        x1 = max(min(num_traces - 1, click[0]), min(num_traces - 1, release[0]))
        new_xlim = (x0, x1)
        y0 = min(max(0, click[1]), max(0, release[1]))
        y1 = max(min(num_samples - 1, click[1]), min(num_samples - 1, release[1]))
        new_ylim = (y1, y0)  # y-axis reversed ...

        if x1 == x0 or y1 == y0:
            # msg = "can't zoom in; selected region too small!"
            # plotUtilities.show_error_message_box(msg)
            return

        self.update_xlim(new_xlim)
        self.update_ylim(new_ylim)
        self.full_redraw()

    def _on_right_rect_click_zoom(
        self,
        eclick: matplotlib.backend_bases.MouseEvent,
        erelease: matplotlib.backend_bases.MouseEvent,
    ) -> None:
        """
        Right click-and-drag zooms out s.t. the region presently displayed
        is shrunk to fit into the box drawn.
        Will not zoom out past image coordinates.
        """
        curr_xlim = self.plot_params.curr_xlim
        curr_ylim = self.plot_params.curr_ylim
        num_traces = self.radar_data.num_traces
        num_samples = self.radar_data.num_samples

        click = self.radar_from_pick_coords((eclick.x, eclick.y))
        release = self.radar_from_pick_coords((erelease.x, erelease.y))
        curr_dx = curr_xlim[1] - curr_xlim[0]
        curr_dy = curr_ylim[0] - curr_ylim[1]  # y-axis reversed ...

        selection_dx = abs(release[0] - click[0])
        selection_dy = abs(release[1] - click[1])
        if selection_dx == 0 or selection_dy == 0:
            # msg = "can't zoom out; selected region too small!"
            # plotUtilities.show_error_message_box(msg)
            return

        scalex = 1.0 * curr_dx / selection_dx
        scaley = 1.0 * curr_dy / selection_dy

        xbar = 0.5 * (curr_xlim[0] + curr_xlim[1])
        ybar = 0.5 * (curr_ylim[0] + curr_ylim[1])
        x0 = max(0, int(xbar - 0.5 * curr_dx * scalex))
        x1 = min(num_traces - 1, int(xbar + 0.5 * curr_dx * scalex))
        y0 = max(0, int(ybar - 0.5 * curr_dy * scaley))
        y1 = min(num_samples - 1, int(ybar + 0.5 * curr_dy * scaley))

        new_xlim = (x0, x1)
        new_ylim = (y1, y0)

        self.update_xlim(new_xlim)
        self.update_ylim(new_ylim)
        self.full_redraw()

    def _on_rect_click_pan(
        self,
        eclick: matplotlib.backend_bases.MouseEvent,
        erelease: matplotlib.backend_bases.MouseEvent,
    ) -> None:
        """left and right clicks both pan identically."""
        xmin, xmax = self.plot_params.curr_xlim
        ymax, ymin = self.plot_params.curr_ylim
        num_traces = self.radar_data.num_traces
        num_samples = self.radar_data.num_samples

        click = self.radar_from_pick_coords((eclick.x, eclick.y))
        release = self.radar_from_pick_coords((erelease.x, erelease.y))
        click_dx = release[0] - click[0]
        click_dy = release[1] - click[1]

        dx = min(xmin, max(click_dx, xmax + 1 - num_traces))
        dy = min(ymin, max(click_dy, ymax + 1 - num_samples))

        self.update_xlim((xmin - dx, xmax - dx))
        self.update_ylim((ymax - dy, ymin - dy))
        self.full_redraw()

    def _on_resize_event(self, event: matplotlib.backend_bases.ResizeEvent) -> None:
        """
        TODO
        """
        assert self.plot_objects.fig is not None
        assert self.plot_objects.radar_ax is not None

        self.plot_params.radar_skip = calc_radar_skip(
            self.plot_objects.fig,
            self.plot_objects.radar_ax,
            self.plot_params.curr_xlim,
        )
        self.full_redraw()

    # TODO: Maybe have this be partly/entirely configurable via plot_params?
    def _on_qt_key_press(self, event: QtGui.QKeyEvent) -> None:
        """
        TODO
        """
        assert self.plot_params.displayed_trace_num is not None
        assert self.plot_params.radar_skip is not None
        if event.key() == QtCore.Qt.Key_F and self.plot_params.trace_visible:
            self.plot_params.trace_frozen = not self.plot_params.trace_frozen
        elif event.key() == QtCore.Qt.Key_G and self.plot_params.crosshair_visible:
            self.plot_params.crosshair_frozen = not self.plot_params.crosshair_frozen
        # And, adding support for enhanced picking =)
        elif event.key() == QtCore.Qt.Key_A:
            # self._on_auto_pick_button_clicked()
            pass
        elif event.key() == QtCore.Qt.Key_S:
            # self._on_save_picks_button_clicked()
            pass
        elif event.key() == QtCore.Qt.Key_E:
            self._on_prev_button_clicked()
        elif event.key() == QtCore.Qt.Key_R:
            self._on_next_button_clicked()
        elif event.key() == QtCore.Qt.Key_Y:
            self._on_full_button_clicked()
        elif event.key() in [
            QtCore.Qt.Key_C,
            QtCore.Qt.Key_D,
            QtCore.Qt.Key_1,
            QtCore.Qt.Key_2,
            QtCore.Qt.Key_3,
            QtCore.Qt.Key_4,
            QtCore.Qt.Key_5,
            QtCore.Qt.Key_6,
            QtCore.Qt.Key_7,
            QtCore.Qt.Key_8,
            QtCore.Qt.Key_9,
        ]:
            # These all require figuring out the mouse postion in the radar ax,
            # so I'm sending them through the same handler.
            # self._on_pick_key_press(event.key())
            pass

        # Using the key press events from the gui, the gui elements get first
        # dibbs on handling 'em. So, can't use left/right... replacing with ,.
        elif (
            event.key() == QtCore.Qt.Key_Comma
            and self.plot_params.trace_visible
            and self.plot_params.trace_frozen
        ):
            self.plot_params.displayed_trace_num -= self.plot_params.radar_skip
            self.update_trace(self.plot_params.displayed_trace_num)
            self.cursor_blit()

        elif (
            event.key() == QtCore.Qt.Key_Period
            and self.plot_params.trace_visible
            and self.plot_params.trace_frozen
        ):
            self.plot_params.displayed_trace_num += self.plot_params.radar_skip
            self.update_trace(self.plot_params.displayed_trace_num)
            self.cursor_blit()

    # TODO: connect to other canvas events ...
    # http://matplotlib.org/users/event_handling.html

    def _on_mouse_mode_group_pressed(self) -> None:
        """
        TODO
        """
        for mode, button in self.plot_objects.mouse_mode_buttons.items():
            if button.isDown():
                self.plot_params.mouse_mode = mode
                self.plot_objects.left_click_rs[mode].set_active(True)
                self.plot_objects.right_click_rs[mode].set_active(True)
            else:
                self.plot_objects.left_click_rs[mode].set_active(False)
                self.plot_objects.right_click_rs[mode].set_active(False)

    def _on_citation_button_clicked(self) -> None:
        """
        Pop up dialog box with metadata about currently-displayed transect.
        """
        assert self.db_campaign is not None
        science_citation = self.db_campaign.science_citation.replace("\n", "<br>")
        citation_info = (
            f"Granule: {self.db_granule.granule_name}"
            "<br><br>"
            f"Institution: {self.db_campaign.institution}"
            "<br><br>"
            f"Campaign: {self.db_campaign.db_campaign}"
            "<br><br>"
            "Data citation:"
            "<br>"
            f"{self.db_campaign.data_citation}"
            "<br><br>"
            "Science citation(s):"
            "<br>"
            f"{science_citation}"
            "<br><br>"
        )

        citation_message_box = QtWidgets.QMessageBox()
        citation_message_box.setWindowTitle("Citation Info")
        citation_message_box.setText(citation_info)
        citation_message_box.setTextFormat(QtCore.Qt.RichText)
        citation_message_box.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        citation_message_box.exec()

    def _on_prev_button_clicked(self) -> None:
        """
        TODO
        """
        xlim = self.plot_params.curr_xlim
        width = xlim[1] - xlim[0]
        shift: float = np.min([0.8 * width, xlim[0]])
        xmin = int(round(xlim[0] - shift))
        xmax = int(round(xlim[1] - shift))
        print(
            f"Clicked prev button. curr_xlim = {xlim}, width = {width}, "
            f"shift = {shift}, new_xlim = {xmin},{xmax}"
        )
        self.update_xlim((xmin, xmax))
        self.full_redraw()

    def _on_full_button_clicked(self) -> None:
        """
        TODO
        """
        self.update_xlim((0, self.radar_data.num_traces - 1))
        self.update_ylim((self.radar_data.num_samples - 1, 0))
        self.full_redraw()

    # TODO: The logic of this is identical to on_prev_button_clicked,
    #   with the only dfiference being a sign. Could combine, into
    #   a scroll_horiz function that takes "direction" as param.
    def _on_next_button_clicked(self) -> None:
        """
        Shift the displayed segment of the radargram to the right,
        with 20% overlap.
        """
        xlim = self.plot_params.curr_xlim
        width = xlim[1] - xlim[0]
        shift: float = np.min([0.8 * width, self.radar_data.num_traces - 1 - xlim[1]])
        xmin = int(round(xlim[0] + shift))
        xmax = int(round(xlim[1] + shift))
        print(
            f"Clicked next button. curr_xlim = {xlim}, width = {width}, "
            f"shift = {shift}, new_xlim = {xmin},{xmax}"
        )
        self.update_xlim((xmin, xmax))
        self.full_redraw()

    def _on_colormap_group_pressed(self) -> None:
        """
        TODO
        """
        assert self.plot_objects.trace_sparkline is not None
        assert self.plot_objects.trace_base is not None
        assert self.plot_objects.crosshair_x is not None
        assert self.plot_objects.crosshair_y is not None
        for cmap, button in self.plot_objects.colormap_buttons.items():
            if button.isDown():
                if self.plot_params.cmap != cmap:
                    self.plot_params.cmap = cmap
                    major = self.plot_config.cmap_major_colors[cmap]
                    minor = self.plot_config.cmap_minor_colors[cmap]
                    self.plot_objects.trace_sparkline.set_major_color(major)
                    self.plot_objects.trace_sparkline.set_minor_color(minor)
                    self.plot_objects.trace_base.set_color(major)
                    self.plot_objects.crosshair_x.set_color(major)
                    self.plot_objects.crosshair_y.set_color(major)
                    self.full_redraw()

    def _on_colormap_changed(self, cmap: str) -> None:
        assert self.plot_objects.trace_sparkline is not None
        assert self.plot_objects.trace_base is not None
        assert self.plot_objects.crosshair_x is not None
        assert self.plot_objects.crosshair_y is not None

        if self.plot_params.cmap != cmap:
            self.plot_params.cmap = cmap
            major = self.plot_config.cmap_major_colors[cmap]
            minor = self.plot_config.cmap_minor_colors[cmap]
            self.plot_objects.trace_sparkline.set_major_color(major)
            self.plot_objects.trace_sparkline.set_minor_color(minor)
            self.plot_objects.trace_base.set_color(major)
            self.plot_objects.crosshair_x.set_color(major)
            self.plot_objects.crosshair_y.set_color(major)
            self.full_redraw()

    def _on_trace_checkbox_changed(self, val: int) -> None:
        """
        Registers / unregisters the trace callback.
        """
        assert self.plot_objects.trace_checkbox is not None
        self.plot_params.trace_visible = self.plot_objects.trace_checkbox.isChecked()
        # Should be responsive when turned back on...
        if self.plot_params.trace_visible:
            self.plot_params.trace_frozen = False
        self.cursor_blit()

    def _on_crosshair_checkbox_changed(self, val: int) -> None:
        """
        Registers / unregisters the crosshair callback, which:
        * is linked with a moving dot on the map view, allowing radar traces
          to be linked with their lat/lon coordinates
        * draws vertical + horizontal lines through the radargram that
          intersect at the mouse's location and make it easier to see
          along-track distance + TWTT.
        """
        assert self.plot_objects.crosshair_checkbox is not None
        self.plot_params.crosshair_visible = (
            self.plot_objects.crosshair_checkbox.isChecked()
        )
        # Should be responsive when turned back on...
        if self.plot_params.crosshair_visible:
            self.plot_params.crosshair_frozen = False  # want it responsive by default.
        self.cursor_blit()

    def _on_button_press_event(
        self, event: matplotlib.backend_bases.MouseEvent
    ) -> None:
        # print("_on_button_press_event")
        self.press_event = event

    def _on_button_release_event(
        self, event: matplotlib.backend_bases.MouseEvent
    ) -> None:
        assert self.press_event is not None
        # print("_on_button_release_event")
        if event.inaxes is not self.plot_objects.pick_ax:
            # print("... but not in our axes! Skipping ...")
            pass
        elif self.plot_params.mouse_mode == "pan":
            self._on_rect_click_pan(self.press_event, event)
        else:  # mouse_mode == "zoom":
            if event.button == matplotlib.backend_bases.MouseButton.LEFT:
                self._on_left_rect_click_zoom(self.press_event, event)
            elif event.button == matplotlib.backend_bases.MouseButton.RIGHT:
                self._on_right_rect_click_zoom(self.press_event, event)
        self.press_event = None

    def _do_nothing(
        self,
        event1: matplotlib.backend_bases.MouseEvent,
        event2: matplotlib.backend_bases.MouseEvent,
    ) -> None:
        """
        We're using the RectangleSelector just for the bounds, since
        the callback was borked in the transition from python2 -> 3.
        So, give it this callback that does nothing.
        """
        pass

    def _on_motion_notify_event(
        self, event: matplotlib.backend_bases.MouseEvent
    ) -> None:
        """
        When mouse moved on radargram, update cursor, trace, and crosshair.
        """
        if event.inaxes is not self.plot_objects.pick_ax:
            return

        trace, sample = self.radar_from_pick_coords((event.x, event.y))
        trace = int(
            np.round(np.min([self.radar_data.num_traces - 1, np.max([0, trace])]))
        )
        sample = int(
            np.round(np.min([self.radar_data.num_samples - 1, np.max([0, sample])]))
        )

        # blitting when neither crosshairs nor trace are active takes ~0.0005.
        # crosshairs is ~0.001, and trace is ~0.005, regardless of whether
        # they changed. So, checking if we need to blit saves up to 5ms.
        trace_changed = self.maybe_update_trace(trace)
        crosshair_changed = self.maybe_update_crosshair(trace, sample)
        if trace_changed or crosshair_changed:
            self.cursor_blit()

        self.update_cursor(trace, sample)

    def _on_clim_slider_changed(self, clim: Tuple[int, int]) -> None:
        """
        TODO
        """
        self.plot_params.clim = clim
        self.full_redraw()

    def _on_quit_button_clicked(self) -> None:
        """
        TODO
        """
        if self.close_cb is not None:
            self.close_cb()
        self.close()

    def _on_xevas_update_x(self, xmin: float, xmax: float) -> None:
        """callback passed to the Xevas selector bars for updating xrange"""
        # xevas selector is [0,1], and we want [0, num_traces).
        # So, subtract 1 before multiplying!
        xlim = (
            int(round((self.radar_data.num_traces - 1) * xmin)),
            int(round((self.radar_data.num_traces - 1) * xmax)),
        )
        self.update_xlim(xlim)
        self.full_redraw()

    def _on_xevas_update_y(self, ymin: float, ymax: float) -> None:
        """callback passed to the Xevas selector bars for updating yrange"""
        # reversed y-axis ...
        # Also, xevas selector is [0,1], and we want [0, num_samples).
        # So, subtract 1 before multiplying!
        ylim = (
            int(round((self.radar_data.num_samples - 1) * (1 - ymin))),
            int(round((self.radar_data.num_samples - 1) * (1 - ymax))),
        )
        self.update_ylim(ylim)
        self.full_redraw()

    # TODO: This code is sloppy about when to keep references or not.
    # I know that QObjects are deleted when they fall out of scope ... but
    # this seems to be working with my sporadic, inconsistent assignments to
    # plot_objects vs local vars ...
    def create_layout(
        self, plot_params: PlotParams, plot_config: PlotConfig
    ) -> PlotObjects:
        """
        Only uses self for connecting callbacks, calling ._on* callbacks, and
        one QtGui call. Does not modify any variables.

        Parameters:
        * plot_params - includes min_val, max_val

        Returns:
        * plot_objects - has all of the objects that we created for the plot.
        """

        # Set up figure & canvas
        plot_objects = PlotObjects()

        plot_objects.main_frame = QtWidgets.QWidget()
        # TODO: I'm not at all sure that this is the right way to handle it ...
        # Should it belong to the canvas instead?
        plot_objects.cursor = QtGui.QCursor()
        plot_objects.main_frame.setCursor(plot_objects.cursor)

        plot_objects.dpi = 100
        # Huh. This seems to only affect the vertical scale of the figure ...
        plot_objects.fig = Figure((18.0, 12.0), dpi=plot_objects.dpi)
        plot_objects.canvas = FigureCanvas(plot_objects.fig)

        # The type needs to be ResizeEvent, but mypy expects Event
        plot_objects.fig.canvas.mpl_connect(
            "resize_event",
            self._on_resize_event,  # type: ignore[arg-type]
        )

        # Used for save button + info about trace/sample of mouse position
        plot_objects.mpl_toolbar = SaveToolbar(
            plot_objects.canvas, plot_objects.main_frame
        )

        # For now, I never want the canvas to have focus, so I can handle all
        # the keypresses through Qt. Some of the widgets can respond anyways,
        # (RectangleSelector, and motion_notify_event), and I use those.
        # https://srinikom.github.io/pyside-docs/PySide/QtGui/QWidget.html#PySide.QtGui.PySide.QtGui.QWidget.focusPolicy
        # plot_objects.canvas.setFocusPolicy(QtCore.Qt.StrongFocus)
        plot_objects.canvas.setFocusPolicy(QtCore.Qt.NoFocus)

        plot_objects.canvas.setParent(plot_objects.main_frame)

        # Variables controlling the layout of the figure where the
        # radargram and xevas bars will be displayed.
        # space between fig edge and xevas bar, and xevas bar and radargram
        margin = 0.01
        # width of xevas bars
        zoom_width = 0.02

        radar_x0 = zoom_width + 2 * margin
        radar_y0 = radar_x0
        radar_dx = 1.0 - radar_x0 - 6 * margin
        radar_dy = 1.0 - radar_y0 - 6 * margin

        # Used purely for blitting, so that the whole region gets restored
        # (sometimes, the sparkline text was going out-of-bounds)
        plot_objects.full_ax = plot_objects.fig.add_axes((0, 0, 1, 1))
        plot_objects.full_ax.axis("off")
        # Don't want to show anything when we're outside the pick_ax
        plot_objects.full_ax.format_coord = lambda x, y: ""  # type: ignore[method-assign]

        plot_objects.radar_ax = plot_objects.fig.add_axes(
            (radar_x0, radar_y0, radar_dx, radar_dy), zorder=1, label="radar"
        )
        plot_objects.radar_ax.xaxis.set_major_formatter(
            FuncFormatter(self.format_xlabel)
        )
        plot_objects.radar_ax.yaxis.set_major_formatter(
            FuncFormatter(self.format_ylabel)
        )
        plot_objects.radar_ax.minorticks_on()
        plot_objects.radar_ax.tick_params(
            which="both",
            direction="out",
            labelbottom=False,
            labeltop=True,
            labelleft=False,
            labelright=True,
            labelsize=8,
            bottom=False,
            top=True,
            left=False,
            right=True,
        )

        # In order to implement picking accepting values just outside the
        # actual axes (required to pick last trace), this axes extends past
        # the radargram, taking up the margin.
        # NOTE(lindzey): This is used for loads of non-pick interactions, so keep it around!
        plot_objects.pick_ax = plot_objects.fig.add_axes(
            (radar_x0 - margin, radar_y0, radar_dx + 2 * margin, radar_dy),
            zorder=3,
            label="pick",
        )
        plot_objects.pick_ax.axis("off")
        # This is the one that shows ... and it's called with units of 0-1
        plot_objects.pick_ax.format_coord = self.format_coord  # type: ignore[method-assign]

        xmargin_frac = margin / radar_dx
        ymargin_frac = abs(margin / radar_dy)

        xevas_horiz_bounds = (
            radar_x0 - margin,
            margin,
            radar_dx + 2 * margin,
            zoom_width,
        )
        plot_objects.xevas_horiz_ax = plot_objects.fig.add_axes(
            xevas_horiz_bounds, projection="unzoomable"
        )
        plot_objects.xevas_horiz_ax.format_coord = lambda x, y: ""  # type: ignore[method-assign]

        xevas_vert_bounds = (
            margin,
            radar_y0 - margin,
            zoom_width,
            radar_dy + 2 * margin,
        )
        plot_objects.xevas_vert_ax = plot_objects.fig.add_axes(
            xevas_vert_bounds, projection="unzoomable"
        )
        plot_objects.xevas_vert_ax.format_coord = lambda x, y: ""  # type: ignore[method-assign]

        # Have to give 0-1 and 1-0 for these to be agnostic to changing x units.
        plot_objects.xevas_horiz = xevas.XevasHorizSelector(
            plot_objects.xevas_horiz_ax,
            0,
            1.0,
            self._on_xevas_update_x,
            margin_frac=xmargin_frac,
        )
        plot_objects.xevas_vert = xevas.XevasVertSelector(
            plot_objects.xevas_vert_ax,
            0,
            1.0,
            self._on_xevas_update_y,
            margin_frac=ymargin_frac,
        )

        # Crosshairs for showing where mouse is on radargram, linked with
        # display on the main deva plot.
        (plot_objects.crosshair_x,) = plot_objects.radar_ax.plot(
            0, 0, "r", linestyle=":", linewidth=2
        )
        (plot_objects.crosshair_y,) = plot_objects.radar_ax.plot(
            0, 0, "r", linestyle=":", linewidth=2
        )

        major_color = self.plot_config.cmap_major_colors[self.plot_params.cmap]
        minor_color = self.plot_config.cmap_minor_colors[self.plot_params.cmap]
        plot_objects.trace_sparkline = sparkline.Sparkline(
            plot_objects.radar_ax,
            units="",
            major_color=major_color,
            minor_color=minor_color,
            scalebar_pos=None,
            scalebar_len=20,
            plot_width=0.1,
            plot_offset=0,
            data_axis="y",
            show_extrema=False,
        )
        (plot_objects.trace_base,) = plot_objects.radar_ax.plot(
            0, 0, "r", linestyle="--"
        )

        # Bars for adding horizontal/vertical scalebars to the radargram itself
        plot_objects.vert_scale = scalebar.Scalebar(
            plot_objects.radar_ax,
            0,
            0,
            0,
            0.01,
            fontsize=18,
            majorcolor="r",
            barstyle="simple",
            coords="frac",
            orientation="vert",
            linewidth=4,
            unit_label="m",
            autoupdate=False,
        )

        plot_objects.horiz_scale = scalebar.Scalebar(
            plot_objects.radar_ax,
            0,
            0,
            0,
            0.01,
            fontsize=18,
            majorcolor="r",
            barstyle="simple",
            coords="frac",
            orientation="horiz",
            linewidth=4,
            unit_label="km",
            autoupdate=False,
        )

        scalebar_label = QtWidgets.QLabel("Scalebars:")

        vert_scale_controls = ScalebarControls(
            self.plot_params.vert_scale_length_m,
            "Vertical",
            "m",
            self.plot_params.vert_scale_x0,
            self.plot_params.vert_scale_y0,
        )
        vert_scale_controls.checked.connect(self._on_vert_scale_checkbox_changed)
        vert_scale_controls.new_length.connect(self._on_vert_scale_new_length)
        vert_scale_controls.new_origin.connect(self._on_vert_scale_new_origin)

        horiz_scale_controls = ScalebarControls(
            self.plot_params.horiz_scale_length_km,
            "Horizontal",
            "km",
            self.plot_params.horiz_scale_x0,
            self.plot_params.horiz_scale_y0,
        )
        horiz_scale_controls.checked.connect(self._on_horiz_scale_checkbox_changed)
        horiz_scale_controls.new_length.connect(self._on_horiz_scale_new_length)
        horiz_scale_controls.new_origin.connect(self._on_horiz_scale_new_origin)

        # TODO: These wil have to be connected to pick_ax, which will
        #  be on top of the various pcor axes.
        # (they only select if it's the top axis ... and the radar one
        # can't be top if we're creating new axes for hte pcor stuff...)
        # (I'm wondering if I'll need to put them on the full_ax, then convert
        # coordinates, in order to support clicking just beyond the axis to get
        # the end of the line...or at least, the pick one...)

        # I'm doing it like this because I want all of 'em to have different
        # line styles....

        # TODO: It'd be cool to use rectprops to change linestyle between
        # zoom in/out, but I didn't immediately see how to do so.
        plot_objects.left_click_rs["zoom"] = mpw.RectangleSelector(
            plot_objects.pick_ax,
            self._do_nothing,
            # drawtype="box",  # This was deprecated in 3.5, and was default anyways
            button=[MouseButton.LEFT],
            useblit=True,
        )
        plot_objects.right_click_rs["zoom"] = mpw.RectangleSelector(
            plot_objects.pick_ax,
            self._do_nothing,
            # drawtype="box",
            button=[MouseButton.RIGHT],
            useblit=True,
        )
        # Pan is the same for both of 'em (it's easier this way)
        plot_objects.left_click_rs["pan"] = mpw.RectangleSelector(
            plot_objects.pick_ax,
            self._do_nothing,
            # TODO: To replicate the old behavior, consider using
            # `rectprops={'visible': False}` and then manually
            # drawing the line
            # drawtype="line",
            button=[MouseButton.LEFT],
            useblit=True,
            # Hacky way to allow "selections" where click/release have the same
            # x or y coordinate, which we do want for panning.
            minspanx=-1,
            minspany=-1,
        )
        plot_objects.right_click_rs["pan"] = mpw.RectangleSelector(
            plot_objects.pick_ax,
            self._do_nothing,
            # drawtype="line",
            button=[MouseButton.RIGHT],
            useblit=True,
            # Hacky way to allow "selections" where click/release have the same
            # x or y coordinate, which we do want for panning.
            minspanx=-1,
            minspany=-1,
        )
        for artist in plot_objects.left_click_rs.values():
            artist.set_active(False)
        for artist in plot_objects.right_click_rs.values():
            artist.set_active(False)

        # This used to be connected/disconnected as the various lines were
        # activated/deactivated, but now that a single one is controlling all
        # of 'em, it's simpler to just leave it connected. Only change that if
        # it turns into a bottleneck...

        # Another place where mypy expects type Event but it needs to be MouseEvent
        plot_objects.canvas.mpl_connect(
            "motion_notify_event",
            self._on_motion_notify_event,  # type: ignore[arg-type]
        )

        # Since the RectangleSelector no longer provides the
        # correct ordering of click/release events to the callback,
        # cache the coordinates, then just use the selector for
        # its drawing/blitting/callback.
        # I think the stubs may be wrong here? The docs say this should be a MouseEvent:
        # https://matplotlib.org/stable/users/explain/figure/event_handling.html
        # but mypy gives an error:
        # Argument 2 to "mpl_connect" of "FigureCanvasBase" has incompatible type
        # "Callable[[MouseEvent], None]"; expected "Callable[[Event], Any]"  [arg-type]
        plot_objects.canvas.mpl_connect(
            "button_press_event",
            self._on_button_press_event,  # type: ignore[arg-type]
        )
        plot_objects.canvas.mpl_connect(
            "button_release_event",
            self._on_button_release_event,  # type: ignore[arg-type]
        )

        # Radio buttons for controlling what mouse clicks mean!
        # (This used to be done w/ their toolbar, but I wanted it to be
        # more explicit, and to have more control on when axes were redrawn.)
        # (Hopefully this also gets rid of the weirdness that ensued when
        # trying to zoom on the xevas bars ... we'll see ...)
        plot_objects.mouse_mode_buttons = {}

        plot_objects.mouse_mode_group = QtWidgets.QButtonGroup()
        mouse_mode_hbox = QtWidgets.QHBoxLayout()
        for mode in ["zoom", "pan"]:
            button = QtWidgets.QRadioButton(mode)
            plot_objects.mouse_mode_buttons[mode] = button
            plot_objects.mouse_mode_group.addButton(button)
            mouse_mode_hbox.addWidget(button)
        plot_objects.mouse_mode_group.buttonPressed.connect(
            self._on_mouse_mode_group_pressed
        )

        # Create text display for cursor
        # TODO: I'm a little nervous including amplitude information,
        # since the different providers seem to use it inconsistently.
        plot_objects.cursor_format = (
            "tr: {:5d}, sa: {:4d}, a: {:0.2f}, twtt: {:5.2f}μs  "
        )
        plot_objects.cursor_label = QtWidgets.QLabel(
            # Can't format {:0.2f} with None
            plot_objects.cursor_format.format(0, 0, 0, 0)
        )
        # This needs to be a fixed-width font so its size doesn't change
        # when the cursor moves. (Changing to a scrollbox for controls rather than a fixed
        # box helped this, but otherwise, updating the text could require redrawing
        # the entire radargram, which is slow.)
        font = QtGui.QFont("Courier New", 12)  # You can use any fixed-width font here
        plot_objects.cursor_label.setFont(font)

        # Create buttons!
        plot_objects.citation_button = QtWidgets.QPushButton("Citation Info")
        plot_objects.citation_button.clicked.connect(
            self._on_citation_button_clicked,
        )

        plot_objects.prev_button = QtWidgets.QPushButton("Prev (e)")
        plot_objects.prev_button.clicked.connect(
            self._on_prev_button_clicked,
        )

        plot_objects.full_button = QtWidgets.QPushButton("Full (y)")
        plot_objects.full_button.clicked.connect(
            self._on_full_button_clicked,
        )

        plot_objects.next_button = QtWidgets.QPushButton("Next (r)")
        plot_objects.next_button.clicked.connect(
            self._on_next_button_clicked,
        )

        controls_hbox = QtWidgets.QHBoxLayout()
        # controls_hbox.addWidget(plot_objects.mpl_toolbar)
        controls_hbox.addWidget(plot_objects.citation_button)
        controls_hbox.addStretch(1)
        controls_hbox.addWidget(plot_objects.cursor_label)
        controls_hbox.addStretch(1)
        controls_hbox.addLayout(mouse_mode_hbox)
        controls_hbox.addWidget(plot_objects.prev_button)
        controls_hbox.addWidget(plot_objects.full_button)
        controls_hbox.addWidget(plot_objects.next_button)

        lower_controls_widget = QtWidgets.QWidget()
        lower_controls_widget.setLayout(controls_hbox)
        lower_controls_scroll_area = QtWidgets.QScrollArea()
        lower_controls_scroll_area.verticalScrollBar().setEnabled(False)
        # The call to setWidgetResizable ensures that addStretch() is
        # respected when the scroll area is larger than necessary for
        # the included widgets.
        lower_controls_scroll_area.setWidgetResizable(True)
        lower_controls_scroll_area.setWidget(lower_controls_widget)

        data_vbox = QtWidgets.QVBoxLayout()
        data_vbox.addWidget(plot_objects.canvas)
        data_vbox.addWidget(lower_controls_scroll_area)

        ####
        # All of the control on the right half of the window
        # This includes sub-boxes for:
        # * appearance (colorscale, data product, channel)
        # * data range sliders
        # * pick mode (pick1/pick2/save)
        # * loading new pick file
        # * which maxima to show
        # * which picks are active

        # switching colormaps
        # TODO: Make this a drop-down to save more space?

        colormap_hbox = QtWidgets.QHBoxLayout()
        colormap_label = QtWidgets.QLabel("Colormap:")
        colormap_hbox.addWidget(colormap_label)
        colormap_combobox = QtWidgets.QComboBox()
        for colormap in plot_config.all_cmaps:
            colormap_combobox.addItem(colormap)
        colormap_combobox.currentTextChanged.connect(self._on_colormap_changed)
        colormap_hbox.addWidget(colormap_combobox)

        # switching which product to display; all options are displayed,
        # but only ones with available data will wind up active.

        # Disabling this now until we fill this in with meaningful
        # data (and possibly support switching high/low gain for UTIG)
        """
        products_vbox = QtWidgets.QVBoxLayout()
        products_label = QtWidgets.QLabel("Radar Products:")
        products_vbox.addWidget(products_label)

        for product in plot_config.all_products:
            plot_objects.product_buttons[product] = QtWidgets.QRadioButton(product)
            plot_objects.product_buttons[product].setEnabled(False)
        plot_objects.product_group = QtWidgets.QButtonGroup()
        for product, button in plot_objects.product_buttons.items():
            plot_objects.product_group.addButton(button)
            products_vbox.addWidget(button)
        plot_objects.product_group.buttonPressed.connect(
            self._on_product_group_pressed,
        )
        """

        # enable/disable the various annotations plotted on the radargram (traces/crosshairs/scalebars)
        annotations_vbox = QtWidgets.QVBoxLayout()
        annotations_label = QtWidgets.QLabel("Annotations:")
        plot_objects.trace_checkbox = QtWidgets.QCheckBox("Traces")
        plot_objects.trace_checkbox.stateChanged.connect(
            self._on_trace_checkbox_changed,
        )
        plot_objects.crosshair_checkbox = QtWidgets.QCheckBox("Crosshairs")
        plot_objects.crosshair_checkbox.stateChanged.connect(
            self._on_crosshair_checkbox_changed,
        )
        annotations_vbox.addWidget(annotations_label)
        annotations_vbox.addWidget(plot_objects.trace_checkbox)
        annotations_vbox.addWidget(plot_objects.crosshair_checkbox)
        annotations_vbox.addStretch(1)  # left-justify this row

        ############

        clim_label = QtWidgets.QLabel("Color Limits:")
        plot_objects.clim_slider = DoubleSlider(new_lim_cb=self._on_clim_slider_changed)

        # Button to exit (the little one in the corner is a PITA.
        quit_hbox = QtWidgets.QHBoxLayout()
        plot_objects.quit_button = QtWidgets.QPushButton("Quit")
        plot_objects.quit_button.clicked.connect(
            self._on_quit_button_clicked,
        )
        quit_hbox.addStretch(1)
        quit_hbox.addWidget(plot_objects.quit_button)

        # Assembling the right vbox ...
        control_vbox = QtWidgets.QVBoxLayout()
        control_vbox.addLayout(colormap_hbox)
        # control_vbox.addWidget(HLine())
        # control_vbox.addLayout(products_vbox)
        control_vbox.addWidget(HLine())
        control_vbox.addLayout(annotations_vbox)
        control_vbox.addWidget(HLine())
        control_vbox.addWidget(clim_label)
        control_vbox.addWidget(plot_objects.clim_slider)
        control_vbox.addWidget(HLine())
        control_vbox.addWidget(scalebar_label)
        control_vbox.addWidget(vert_scale_controls)
        control_vbox.addWidget(horiz_scale_controls)
        control_vbox.addStretch(1)
        control_vbox.addWidget(HLine())
        control_vbox.addStretch(1)
        control_vbox.addLayout(quit_hbox)

        control_scroll_widget = QtWidgets.QWidget()
        control_scroll_widget.setLayout(control_vbox)
        control_scroll_area = QtWidgets.QScrollArea()
        control_scroll_area.setWidget(control_scroll_widget)

        ####
        # Put it all together.
        hbox = QtWidgets.QHBoxLayout()
        hbox.addLayout(data_vbox, 1)  # I want this one to stretch
        hbox.addWidget(control_scroll_area)
        plot_objects.main_frame.setLayout(hbox)

        self.setCentralWidget(plot_objects.main_frame)

        #############

        return plot_objects

    def format_xlabel(self, trace: float, pos: int) -> str:
        """
        This maps traces to time since start of transect.
        It would be cool to also do distance, but that requires pulling more
        data sources into radarFigure than I'm comfortable with ... it's meant
        to be as lightweight as possible for looking at radar data.
        """
        # TODO: Why do we have the pos argument that's not used?
        # TODO: This needs to obey whatever x-axis is currently in use

        # TODO: This is elapsed time into flight; better to replace
        # it with actual year/date?
        int_trace = min(max(0, int(round(trace))), self.radar_data.num_traces - 1)

        try:
            # NOTE(lindzey): I think the previous implementation was broken,
            #   since it gave distance between first point in transect and the
            #   point cooresponding to the x-coordinate, rather than a proper
            #   sum along the entire transect.
            # dist = self.transect_data.rpc.along_track_dist([0, xx], "traces")
            all_dists = self.radar_data.along_track_dist()
            dist = all_dists[int_trace]
            label = f"{dist / 1000.0:0.1f} km"

            # It appears that the BAS data's utc data isn't what I expected,
            # so I can't convert to minutes or date.
            # At least for polargap, the time on a transect only covers < 1 sec.
            # (Julien says that he has fixed that issue, but the data probably hasn't
            # been pushed yet)

            # if self.radar_data.utc is not None:
            #     t0 = self.radar_data.utc[0]
            #     t1 = self.radar_data.utc[int_trace]
            #     minutes, seconds = divmod(t1 - t0, 60)
            #     # Must first convert to float; otherwise get error:
            #     # TypeError: 'numpy.float32' object cannot be interpreted as an integer
            #     time_str = datetime.datetime.fromtimestamp(float(t1)).strftime(
            #         # BAS's timestamps aren't posix. I think they're since midnight?
            #         # So, for now, just commenting this out so we can see time elapsed.
            #         # "%Y-%m-%d\n%H:%M:%S"
            #         "%H:%M:%S"
            #     )
            #     # label = "\n".join([label, time_str])

            return label

            # print(
            #     f"Requested trace {trace}: closest valid is {int_trace}"
            #     f"along-track dist is: {dist}, and time for {t1} is {time_str}"
            # )
        except Exception:
            raise Exception(
                f"Trying to format label. input trace = {trace}, type is {type(trace)}. Rounds to {int_trace} for radargram with {self.radar_data.num_traces} traces and {self.radar_data.num_samples} samples"
            )

    def format_ylabel(self, yy: float, _pos: float) -> str:
        """
        Convert samples to microseconds and display as the Y axis label
        """
        nearest_sample = min(max(0, int(np.round(yy))), self.radar_data.num_samples - 1)
        sample_time_us = self.radar_data.fast_time_us[nearest_sample]
        # dz = sample_time_us * 169 * 0.5
        # print(
        #     f"For {yy}, nearest_sample = {nearest_sample}, "
        #     f"sample_time = {sample_time_us} and depth = {dz}"
        # )
        # Hacky way to get a newline inside a raw string
        return "\n".join([f"{sample_time_us:.2f}", r"$\mu$s"])

    def format_coord(self, x: float, y: float) -> str:
        assert self.plot_objects.pick_ax is not None
        xd, yd = self.plot_objects.pick_ax.transData.transform([x, y])
        trace, sample = self.radar_from_pick_coords((xd, yd))
        counts = self.radar_data.data[trace, sample]
        return "trace=%d sample=%d (%d counts)" % (trace, sample, counts)

    def _on_vert_scale_checkbox_changed(self, checked: bool) -> None:
        """
        TODO
        """
        self.plot_params.vert_scale_visible = checked
        # TODO: This may call setChecked(False), which seems to disable the
        # callback the next time around ... but it works again on the 2nd click.
        self.data_blit()

    def _on_horiz_scale_checkbox_changed(self, checked: bool) -> None:
        """
        TODO
        """
        self.plot_params.horiz_scale_visible = checked
        # TODO: This may call setChecked(False), which seems to disable the
        # callback the next time around ... but it works again on the 2nd click.
        self.data_blit()

    def _on_vert_scale_new_length(self, length: float) -> None:
        """
        Update plot_objects with new length and redraw, after sanity checking.
        """
        if length <= 0:
            msg = "Please enter positive length"
            raise Exception(msg)

        if length != self.plot_params.vert_scale_length_m:
            self.plot_params.vert_scale_length_m = length
            self.data_blit()

    def _on_horiz_scale_new_length(self, length: float) -> None:
        """
        Update plot_objects with new length and redraw
        """
        if length != self.plot_params.horiz_scale_length_km:
            self.plot_params.horiz_scale_length_km = length
            self.data_blit()

    def _on_vert_scale_new_origin(self, x0: float, y0: float) -> None:
        """
        Update vertical scalebar with new x0, y0 and redraw
        """
        if x0 < 0.0 or x0 > 1.0:
            msg = "Please enter x0 in range [0, 1]"
            raise Exception(msg)

        if y0 < 0.0 or y0 > 1.0:
            msg = "Please enter y0 in range [0, 1]"
            raise Exception(msg)

        needs_blit = False
        if x0 != self.plot_params.vert_scale_x0:
            self.plot_params.vert_scale_x0 = x0
            needs_blit = True
        if y0 != self.plot_params.vert_scale_y0:
            self.plot_params.vert_scale_y0 = y0
            needs_blit = True
        if needs_blit:
            self.data_blit()

    # This is crying out for a lambda taking the textbox object and the var it
    # goes into ...
    def _on_horiz_scale_new_origin(self, x0: float, y0: float) -> None:
        """
        Update plot_objects with new x0 and redraw
        """
        needs_blit = False
        if x0 != self.plot_params.horiz_scale_x0:
            self.plot_params.horiz_scale_x0 = x0
            needs_blit = True
        if y0 != self.plot_params.horiz_scale_y0:
            self.plot_params.horiz_scale_y0 = y0
            needs_blit = True
        if needs_blit:
            self.data_blit()

    def plot_scalebars(self) -> None:
        """
        TODO
        """
        assert self.plot_objects.radar_ax is not None
        assert self.plot_objects.vert_scale is not None
        assert self.plot_objects.horiz_scale is not None

        xlim = tuple(map(int, self.plot_objects.radar_ax.get_xlim()))
        ylim = tuple(map(int, self.plot_objects.radar_ax.get_ylim()))

        all_dists = self.radar_data.along_track_dist()
        dist0 = all_dists[xlim[0]]
        dist1 = all_dists[xlim[1]]
        data_width = dist1 - dist0  # in meters

        all_ranges = 169 * self.radar_data.fast_time_us / 2.0  # in meters
        range0 = all_ranges[ylim[0]]
        range1 = all_ranges[ylim[1]]
        data_height = np.abs(range1 - range0)

        self.plot_objects.vert_scale.set_length(
            self.plot_params.vert_scale_length_m, data_height
        )
        self.plot_objects.vert_scale.set_origin(
            self.plot_params.vert_scale_x0, self.plot_params.vert_scale_y0
        )
        self.plot_objects.vert_scale.update()

        self.plot_objects.horiz_scale.set_length(
            self.plot_params.horiz_scale_length_km, (data_width / 1000.0)
        )
        self.plot_objects.horiz_scale.set_origin(
            self.plot_params.horiz_scale_x0, self.plot_params.horiz_scale_y0
        )
        self.plot_objects.horiz_scale.update()

        for element in self.plot_objects.vert_scale.elements.values():
            self.plot_objects.radar_ax.draw_artist(element)
        for element in self.plot_objects.horiz_scale.elements.values():
            self.plot_objects.radar_ax.draw_artist(element)
