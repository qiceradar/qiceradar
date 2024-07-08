#! /usr/bin/env python3

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

import argparse
import datetime
import pathlib
import sqlite3
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib as mpl
import matplotlib.backend_bases
import numpy as np

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
from .datautils import radar_utils
from .datautils import db_utils

# This breaks it on the command line, but works with QGIS.
from .mplUtilities import (
    SaveToolbar,
    XevasHorizSelector,
    XevasVertSelector,
    get_ax_shape,
)
from .plotUtilities import HLine, VLine, show_error_message_box
from .plotutils import scalebar, sparkline
from .radarWidgets import DoubleSlider

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

    def __init__(self) -> None:
        self.curr_xlim = None  # type: Optional[Tuple[int, int]]
        self.curr_ylim = None  # type: Optional[Tuple[int, int]]
        # how many traces are skipped between the displayed traces
        self.radar_skip = None  # type: Optional[int]

        # which trace the camera cursor should currently be on.
        self.displayed_trace_num = None  # type: Optional[int]

        # Whether these positions should be frozen or updated as the mouse moves
        self.crosshair_frozen = False
        self.trace_frozen = False

        # Whether these should be visible ..
        self.crosshair_visible = False
        self.trace_visible = False

        self.vert_scale_visible = False
        self.vert_scale_length: float = 500.0  # Units of m
        # Units of axis-fraction
        self.vert_scale_x0 = 0.05
        self.vert_scale_y0 = 0.1
        self.horiz_scale_visible = False
        self.horiz_scale_length: float = 10.0  # Units of km
        # units of axis-fraction
        self.horiz_scale_x0 = 0.1
        self.horiz_scale_y0 = 0.05

        self.product = None  # type: Optional[str]

        self.cmap = "gray"
        self.clim = (0, 1)  # what's currently displayed
        self.cmin = 0  # min val from radar
        self.cmax = 1  # max val from radar

        self.mouse_mode = "zoom"

    def initialize_from_radar(self, radar_data: radar_utils.RadarData) -> None:
        """
        Called to initialize the plotting parameters to match the
        limits implied by the radargram. Only called at the start - we don't
        want the plots to change as a function of reloading data.
        # TODO: Maybe have clim change, but not xlim, for reloading? ... the
        # pik1/1m change is a bigger, more annoying, problem.
        """
        self.product = radar_data.available_products[0]
        self.curr_xlim = (0, radar_data.num_traces - 1)
        self.curr_ylim = (radar_data.num_samples - 1, 0)

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
        self.main_frame = None  # type: Optional[QtWidgets.QWidget]
        self.cursor = None  # type: Optional[QtGui.QCursor]

        self.fig = None  # type: Optional[Figure]
        self.canvas = None  # type: Optional[FigureCanvas]
        self.mpl_toolbar = None  # type: Optional[SaveToolbar]
        self.radar_plot = None  # type: Optional[mpl.image.AxesImage]

        self.dpi = None  # type: Optional[int]

        self.full_ax = None  # type: Optional[mpl.axes.Axes]
        self.radar_ax = None  # type: Optional[mpl.axes.Axes]
        self.xevas_horiz_ax = None  # type: Optional[mpl.axes.Axes]
        self.xevas_vert_ax = None  # type: Optional[mpl.axes.Axes]

        self.xevas_horiz: Optional[XevasHorizSelector] = None
        self.xevas_vert = None  # type: Optional[XevasVertSelector]

        self.crosshair_x = None  # type: Optional[mpl.lines.Line2D]
        self.crosshair_y = None  # type: Optional[mpl.lines.Line2D]

        self.trace_sparkline: Optional[sparkline.Sparkline] = None
        self.trace_base = None  # type: Optional[mpl.lines.Line2D]
        self.simple_rcoeff_sparkline: Optional[sparkline.Sparkline] = None
        self.rcoeff_sparkline = None

        self.left_click_rs = {}  # type: Dict[str, mpw.RectangleSelector]
        self.right_click_rs = {}  # type: Dict[str, mpw.RectangleSelector]

        self.mouse_mode_buttons = {}  # type: Dict[str, QtWidgets.QRadioButton]
        self.mouse_mode_group = None  # type: Optional[QtWidgets.QButtonGroup]

        self.citation_button = None  # type: Optional[QtWidgets.QPushButton]
        self.prev_button = None  # type: Optional[QtWidgets.QPushButton]
        self.full_button = None  # type: Optional[QtWidgets.QPushButton]
        self.next_button = None  # type: Optional[QtWidgets.QPushButton]

        self.colormap_buttons = {}  # type: Dict[str, QtWidgets.QRadioButton]
        self.colormap_group = None  # type: Optional[QtWidgets.QButtonGroup]

        self.product_buttons = {}  # type: Dict[str, QtWidgets.QRadioButton]
        self.product_group = None  # type: Optional[QtWidgets.QButtonGroup]

        self.trace_checkbox = None  # type: Optional[QtWidgets.QCheckBox]
        self.crosshair_checkbox = None  # type: Optional[QtWidgets.QCheckBox]

        self.clim_label = None
        self.clim_slider = None  # type: Optional[DoubleSlider]

        self.vert_scale_checkbox = None  # type: Optional[QtWidgets.QCheckBox]
        self.vert_scale_length_label = None  # type: Optional[QtWidgets.QLabel]
        self.vert_scale_length_textbox = None  # type: Optional[QtWidgets.QLineEdit]
        self.vert_scale_origin_label = None  # type: Optional[QtWidgets.QLabel]
        self.vert_scale_x0_textbox = None  # type: Optional[QtWidgets.QLineEdit]
        self.vert_scale_y0_textbox = None  # type: Optional[QtWidgets.QLineEdit]

        self.horiz_scale_checkbox = None  # type: Optional[QtWidgets.QCheckBox]
        self.horiz_scale_length_label = None  # type: Optional[QtWidgets.QLabel]
        self.horiz_scale_length_textbox = None  # type: Optional[QtWidgets.QLineEdit]
        self.horiz_scale_origin_label = None  # type: Optional[QtWidgets.QLabel]
        self.horiz_scale_x0_textbox = None  # type: Optional[QtWidgets.QLineEdit]
        self.horiz_scale_y0_textbox = None  # type: Optional[QtWidgets.QLineEdit]

        self.vert_scale = None  # type: Optional[scalebar.Scalebar]
        self.horiz_scale = None  # type: Optional[scalebar.Scalebar]

        self.quit_button = None  # type: Optional[QtWidgets.QPushButton]

        self.annotations_label = None  # type: Optional[QtWidgets.QLabel]
        self.annotations_vbox = None  # type: Optional[QtWidgets.QHBoxLayout]


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


class BasicRadarWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        filepath: pathlib.Path,  # Fully-specified path
        db_granule: db_utils.DatabaseGranule,
        db_campaign: db_utils.DatabaseCampaign,
        parent_xlim_changed_cb: Optional[
            Callable[[List[Tuple[float, float]]], None]
        ] = None,
        parent_cursor_cb: Optional[Callable[[float, float], None]] = None,
        close_cb: Optional[Callable[[None], None]] = None,
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
        super(BasicRadarWindow, self).__init__()

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
        self.plot_params = PlotParams()
        self.plot_params.initialize_from_radar(self.radar_data)

        # Set up the visual display, and hook up all the callbacks.
        # TODO: get rid of dependence on plot_params.available_products?
        self.plot_objects = self.create_layout(self.plot_params, self.plot_config)

        # This needs to come after initialize_from_radar, b/c it depends on xlim
        # TODO: silly to pass radar_data just for
        self.initialize_gui_from_params_data(self.plot_params, self.plot_config)

        # This is annoying, because it depends on and modifies plot_params
        # However, I think that all that matters is that the fig and ax exist,
        # not their state.
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
        if type(event) == QtGui.QKeyEvent:
            self._on_qt_key_press(event)
            # By doing this here, we don't let anybody downstream of this
            # catch 'em. If I wanted to allow that, move event.accept()
            # into the callback so we only accept keypresses that it handles.
            event.accept()
        else:
            event.ignore()

    def maybe_update_trace(self, trace_num: int) -> bool:
        """
        Called if we want to check for frozen before moving the trace.
        """
        if self.plot_params.trace_visible and not self.plot_params.trace_frozen:
            self.update_trace(trace_num)
            return True
        else:
            return False

    def initialize_gui_from_params_data(
        self, plot_params: PlotParams, plot_config: PlotConfig
    ) -> None:
        """
        This just sets the current state of various GUI widgets based on:
        * plot params - initial state of buttons
        * transect_data - used for pickfile names, available radar products
        (Yeah, I could just access self.plot_params, but I want the call
        signature to be explicit what it depends on.)
        """
        # TODO(lindzey): Shouldn't need this input list if we only
        #  create the appropriate buttons given the dataset.
        for product in plot_config.all_products:
            self.plot_objects.product_buttons[product].setEnabled(True)

        self.plot_objects.product_buttons[plot_params.product].setChecked(True)
        self.plot_objects.colormap_buttons[plot_params.cmap].setChecked(True)
        self.plot_objects.mouse_mode_buttons[plot_params.mouse_mode].setChecked(True)
        mouse_mode = self.plot_params.mouse_mode
        self.plot_objects.left_click_rs[mouse_mode].set_active(True)
        self.plot_objects.right_click_rs[mouse_mode].set_active(True)

        self.plot_objects.radar_ax.set_xlim(plot_params.curr_xlim)
        self.plot_objects.radar_ax.set_ylim(plot_params.curr_ylim)

        self.plot_objects.clim_slider.set_range((plot_params.cmin, plot_params.cmax))
        self.plot_objects.clim_slider.set_value(plot_params.clim)

    def update_trace(self, trace_num: int) -> None:
        """
        Center trace on median, scaled to take up 1/16th of display..
        Raw values are reported in dBm, with a season-dependent offset.
        """
        self.plot_params.displayed_trace_num = trace_num

        # TODO: Need to figure out conversion from counts to dB in order to
        # label the trace sparkline. In the meantime, set to 0.
        # TODO(lindzey): consider calculating a reasonable scale + offset
        # from the data itself?
        # offset = radarAnalysis.channel_offsets[self.plot_params.channel]
        offset = 0
        trace_dB = self.radar_data.data[trace_num, :] / 1000.0 + offset
        yy = np.arange(0, self.radar_data.num_samples)

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
        # update_selection doesn't trigger any cbs.
        num_traces = self.radar_data.num_traces
        self.plot_objects.xevas_horiz.update_selection(
            (1.0 * new_xlim[0] / (num_traces - 1), 1.0 * new_xlim[1] / (num_traces - 1))
        )

    def update_ylim(self, new_ylim: Tuple[int, int]) -> None:
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
        data = self.radar_data.data
        xlim = self.plot_params.curr_xlim
        ylim = self.plot_params.curr_ylim
        radar_skip = self.plot_params.radar_skip
        self.plot_objects.radar_plot.set_data(
            data[xlim[0] : xlim[1] : radar_skip, ylim[1] : ylim[0]].T
        )
        extent = np.append(xlim, ylim)
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
        self.plot_objects.canvas.restore_region(self.radar_restore)

        self.data_set_visible(self.plot_objects, self.plot_params)
        # TODO: If this series starts getting too slow, move the "set_data"
        # logic back to the callbacks that change it. However, there are
        # enough things that change the picks/max values that it's a lot
        # simpler to put all of that right here.

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

    # These were used for the various picking plot objects.
    # leaving around in case we need to add something that behaves
    # like those for blitting.
    def data_set_invisible(self, plot_objects: PlotObjects) -> None:
        return

    # TODO(lindzey): It's weird that we need params to set visible, but not for invisible.
    def data_set_visible(
        self, plot_objects: PlotObjects, plot_params: PlotParams
    ) -> None:
        return

    def cursor_set_invisible(self, plot_objects: PlotObjects) -> None:
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
        # I tried precalculating this, but it was awkward to make sure it got
        # initialized correctly. It takes < 0.2ms per call, so I'm OK with
        # that penalty. Putting it in initialize_gui_from_params_data just
        # after set_{xlim,ylim} didn't do it.
        inv = self.plot_objects.radar_ax.transData.inverted()
        p0 = inv.transform(pick)
        xlim = self.plot_params.curr_xlim
        ylim = self.plot_params.curr_ylim
        xx = min(xlim[1], max(xlim[0], int(round(p0[0]))))
        # Tricksy .. axis reversed!
        yy = max(ylim[1], min(ylim[0], int(round(p0[1]))))
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
        if event.key() == QtCore.Qt.Key_F and self.plot_params.trace_visible:
            self.plot_params.trace_frozen = not self.plot_params.trace_frozen
        elif event.key() == QtCore.Qt.Key_G and self.plot_params.crosshair_visible:
            self.plot_params.crosshair_frozen = not self.plot_params.crosshair_frozen
        # And, adding support for enhanced picking =)
        elif event.key() == QtCore.Qt.Key_A:
            self._on_auto_pick_button_clicked()
        elif event.key() == QtCore.Qt.Key_S:
            self._on_save_picks_button_clicked()
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
            self._on_pick_key_press(event.key())

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
        shift = np.min([0.8 * width, xlim[0]])
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
        shift = np.min([0.8 * width, self.radar_data.num_traces - 1 - xlim[1]])
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

    def _on_product_group_pressed(self) -> None:
        """
        TODO
        """
        old_product = self.plot_params.product
        for new_product, button in self.plot_objects.product_buttons.items():
            if button.isDown():
                if self.plot_params.product != new_product:
                    prev_xlim = self.plot_params.curr_xlim

                    prev_num_traces = self.radar_data.num_traces
                    self.plot_params.product = new_product
                    # TODO: This needs to be updated!
                    self.radar_data = radar_utils.RadarData(
                        self.pst, new_product, self.plot_params.channel
                    )
                    new_num_traces = self.radar_data.num_traces

                    # Converting bounds is trickier than you might think because
                    # it has to result in integers, which leads to propagating
                    # rounding errors.

                    # We used to do this for 1m/pik1, and if we decide to support
                    # BAS's pulse data, we may have to do that as well.
                    # if prev_1m and not new_1m:
                    #     # Have to be careful here to be consistent ... w/o the
                    #     # ceil, repeately converting between the two caused the
                    #     # boundaries to drift slightly.
                    #     new_xcoords = self.transect_data.rtc.convert(
                    #         list(prev_xlim), "traces_1m", "traces_pik1"
                    #     )
                    #     new_xlim = (np.ceil(new_xcoords[0]), np.ceil(new_xcoords[1]))
                    # elif new_1m and not prev_1m:
                    #     # Have to be careful here - each pik1 sweep points to
                    #     # the middle of the range of 1m sweeps used to generate
                    #     # it, so we want to make the boundary the midpoint.
                    #     xcoords = [
                    #         prev_xlim[0] - 1,
                    #         prev_xlim[0],
                    #         prev_xlim[1] - 1,
                    #         prev_xlim[1],
                    #     ]
                    #     # This awkwardness is for mypy type checking - convert takes floats!
                    #     new_xcoords = self.transect_data.rtc.convert(
                    #         [float(xc) for xc in xcoords], "traces_pik1", "traces_1m"
                    #     )
                    #     new_xlim = (
                    #         int(np.round(np.mean(new_xcoords[0:2]))),
                    #         int(np.round(np.mean(new_xcoords[2:4]))),
                    #     )
                    # else:
                    #     new_xlim = prev_xlim
                    new_xlim = prev_xlim

                    # If we're at the start/end of the PST, want new display
                    # to also include all data ....
                    if prev_xlim[0] == 0:
                        new_xlim = (0, new_xlim[1])
                    if prev_xlim[-1] >= prev_num_traces - 1:
                        new_xlim = (new_xlim[0], new_num_traces - 1)

                    self.update_xlim(new_xlim)
                    self.plot_params.update_clim_from_radar(self.radar_data)
                    self.plot_params.rcoeff_needs_recalc = True

                    # This recalculates skip and sets data based on curr_xlim
                    self.full_redraw()

    def _on_trace_checkbox_changed(self, val: int) -> None:
        """
        Registers / unregisters the trace callback.
        """
        self.plot_params.trace_visible = self.plot_objects.trace_checkbox.isChecked()
        # Should be responsive when turned back on...
        if self.plot_params.trace_visible:
            self.plot_params.trace_frozen = False
        self.cursor_blit()

    def _on_crosshair_checkbox_changed(self, val: int) -> None:
        """
        TODO
        """
        self.plot_params.crosshair_visible = (
            self.plot_objects.crosshair_checkbox.isChecked()
        )
        # Should be responsive when turned back on...
        if self.plot_params.crosshair_visible:
            self.plot_params.crosshair_frozen = False  # want it responsive by default.
        self.cursor_blit()

    def _on_motion_notify_event(
        self, event: matplotlib.backend_bases.MouseEvent
    ) -> None:
        """
        When mouse moved on radargram, update trace and crosshair.
        """
        # if event.inaxes is not self.plot_objects.pick_ax:
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
        # This can't go any earlier, or else I'll get errors about fig not having canvas
        plot_objects.fig.canvas.mpl_connect("resize_event", self._on_resize_event)
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
        plot_objects.full_ax = plot_objects.fig.add_axes([0, 0, 1, 1])
        plot_objects.full_ax.axis("off")
        # Don't want to show anything when we're outside the pick_ax
        plot_objects.full_ax.format_coord = lambda x, y: ""

        plot_objects.radar_ax = plot_objects.fig.add_axes(
            [radar_x0, radar_y0, radar_dx, radar_dy], zorder=1, label="radar"
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
            [radar_x0 - margin, radar_y0, radar_dx + 2 * margin, radar_dy],
            zorder=3,
            label="pick",
        )
        plot_objects.pick_ax.axis("off")
        # This is the one that shows ... and it's called with units of 0-1
        plot_objects.pick_ax.format_coord = self.format_coord

        xmargin_frac = margin / radar_dx
        ymargin_frac = abs(margin / radar_dy)

        xevas_horiz_bounds = [
            radar_x0 - margin,
            margin,
            radar_dx + 2 * margin,
            zoom_width,
        ]
        plot_objects.xevas_horiz_ax = plot_objects.fig.add_axes(
            xevas_horiz_bounds, projection="unzoomable"
        )
        plot_objects.xevas_horiz_ax.format_coord = lambda x, y: ""

        xevas_vert_bounds = [
            margin,
            radar_y0 - margin,
            zoom_width,
            radar_dy + 2 * margin,
        ]
        plot_objects.xevas_vert_ax = plot_objects.fig.add_axes(
            xevas_vert_bounds, projection="unzoomable"
        )
        plot_objects.xevas_vert_ax.format_coord = lambda x, y: ""

        # Have to give 0-1 and 1-0 for these to be agnostic to changing x units.
        plot_objects.xevas_horiz = XevasHorizSelector(
            plot_objects.xevas_horiz_ax,
            0,
            1.0,
            self._on_xevas_update_x,
            margin_frac=xmargin_frac,
        )
        plot_objects.xevas_vert = XevasVertSelector(
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
            units="dB",
            major_color=major_color,
            minor_color=minor_color,
            scalebar_pos=[0.85, 0.95],
            scalebar_len=20,
            plot_width=0.0625,
            plot_offset=0,
            data_axis="y",
        )
        (plot_objects.trace_base,) = plot_objects.radar_ax.plot(
            0, 0, "r", linestyle="--"
        )

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
            self._on_left_rect_click_zoom,
            drawtype="box",
            button=[1],
        )
        plot_objects.right_click_rs["zoom"] = mpw.RectangleSelector(
            plot_objects.pick_ax,
            self._on_right_rect_click_zoom,
            drawtype="box",
            button=[3],
        )
        # Pan is the same for both of 'em (it's easier this way)
        plot_objects.left_click_rs["pan"] = mpw.RectangleSelector(
            plot_objects.pick_ax, self._on_rect_click_pan, drawtype="line", button=[1]
        )
        plot_objects.right_click_rs["pan"] = mpw.RectangleSelector(
            plot_objects.pick_ax, self._on_rect_click_pan, drawtype="line", button=[3]
        )
        for artist in plot_objects.left_click_rs.values():
            artist.set_active(False)
        for artist in plot_objects.right_click_rs.values():
            artist.set_active(False)

        # This used to be connected/disconnected as the various lines were
        # activated/deactivated, but now that a single one is controlling all
        # of 'em, it's simpler to just leave it connected. Only change that if
        # it turns into a bottleneck...
        plot_objects.canvas.mpl_connect(
            "motion_notify_event", self._on_motion_notify_event
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
        controls_hbox.addLayout(mouse_mode_hbox)
        controls_hbox.addWidget(plot_objects.prev_button)
        controls_hbox.addWidget(plot_objects.full_button)
        controls_hbox.addWidget(plot_objects.next_button)

        data_vbox = QtWidgets.QVBoxLayout()
        data_vbox.addWidget(plot_objects.canvas)
        data_vbox.addLayout(controls_hbox)

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

        colormap_vbox = QtWidgets.QVBoxLayout()
        colormap_label = QtWidgets.QLabel("Colormaps:")
        colormap_vbox.addWidget(colormap_label)

        for colormap in plot_config.all_cmaps:
            plot_objects.colormap_buttons[colormap] = QtWidgets.QRadioButton(colormap)

        plot_objects.colormap_group = QtWidgets.QButtonGroup()
        for cmap, button in plot_objects.colormap_buttons.items():
            plot_objects.colormap_group.addButton(button)
            colormap_vbox.addWidget(button)
        plot_objects.colormap_group.buttonPressed.connect(
            self._on_colormap_group_pressed,
        )

        # switching which product to display; all options are displayed,
        # but only ones with available data will wind up active.

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

        # enable/disable the various annotations plotted on the radargram (traces/crosshairs/scalebars)
        plot_objects.annotations_vbox = QtWidgets.QVBoxLayout()
        plot_objects.annotations_label = QtWidgets.QLabel("Annotations:")
        plot_objects.trace_checkbox = QtWidgets.QCheckBox("Traces")
        plot_objects.trace_checkbox.stateChanged.connect(
            self._on_trace_checkbox_changed,
        )
        plot_objects.crosshair_checkbox = QtWidgets.QCheckBox("Crosshairs")
        plot_objects.crosshair_checkbox.stateChanged.connect(
            self._on_crosshair_checkbox_changed,
        )
        plot_objects.annotations_vbox.addWidget(plot_objects.annotations_label)
        plot_objects.annotations_vbox.addWidget(plot_objects.trace_checkbox)
        plot_objects.annotations_vbox.addWidget(plot_objects.crosshair_checkbox)
        plot_objects.annotations_vbox.addStretch(1)  # left-justify this rowx

        ############

        plot_objects.clim_label = QtWidgets.QLabel("Color Limits:")
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
        control_vbox.addLayout(colormap_vbox)
        control_vbox.addWidget(HLine())
        control_vbox.addLayout(products_vbox)
        control_vbox.addWidget(HLine())
        control_vbox.addLayout(plot_objects.annotations_vbox)
        control_vbox.addWidget(HLine())
        control_vbox.addWidget(plot_objects.clim_label)
        control_vbox.addWidget(plot_objects.clim_slider)
        control_vbox.addWidget(HLine())
        control_vbox.addStretch(1)
        control_vbox.addLayout(quit_hbox)

        ####
        # Put it all together.
        hbox = QtWidgets.QHBoxLayout()
        hbox.addLayout(data_vbox, 1)  # I want this one to stretch
        hbox.addLayout(control_vbox)
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
            #   since it gave distance between first poitn in transect and the
            #   point cooresponding to the x-coordinate, rather than a proper
            #   sum along the entire transect.
            # dist = self.transect_data.rpc.along_track_dist([0, xx], "traces")
            all_dists = self.radar_data.along_track_dist()
            dist = all_dists[int_trace]
            label = f"{dist/1000.0:0.1f} km"

            # It appears that the BAS data's utc data isn't what I expected,
            # so I can't convert to minutes or date.
            # At least for polargap, the time on a transect only covers < 1 sec.
            if self.radar_data.utc is not None:
                t0 = self.radar_data.utc[0]
                t1 = self.radar_data.utc[int_trace]
                minutes, seconds = divmod(t1 - t0, 60)
                time_str = datetime.datetime.fromtimestamp(t1).strftime(
                    # BAS's timestamps aren't posix. I think they're since midnight?
                    # So, for now, just commenting this out so we can see time elapsed.
                    # "%Y-%m-%d\n%H:%M:%S"
                    "%H:%M:%S"
                )
                # label = "\n".join([label, time_str])

            # label = "\n".join([label, f"{int_trace}"])

            return label

            # print(
            #     f"Requested trace {trace}: closest valid is {int_trace}"
            #     f"along-track dist is: {dist}, and time for {t1} is {time_str}"
            # )
        except Exception as ex:
            raise Exception(
                f"Trying to format label. input trace = {trace}, type is {type(trace)}. Rounds to {int_trace} for radargram with {self.radar_data.num_traces} traces and {self.radar_data.num_samples} samples"
            )

    def format_ylabel(self, yy: float, _pos: float) -> str:
        """
        We sample at 50MHz, so each sample is 20ns, or 0.02us
        In ice, this translates to a one-way distance of 0.02*169/2
        """
        nearest_sample = min(max(0, int(np.round(yy))), self.radar_data.num_samples - 1)
        sample_time_us = self.radar_data.fast_time_us[nearest_sample]
        dz = sample_time_us * 169 * 0.5
        # print(
        #     f"For {yy}, nearest_sample = {nearest_sample}, "
        #     f"sample_time = {sample_time_us} and depth = {dz}"
        # )
        return "%0.2f us\n%d m" % (sample_time_us, dz)

    def format_coord(self, xx: float, yy: float) -> None:
        coord = self.plot_objects.pick_ax.transData.transform([xx, yy])
        trace, sample = self.radar_from_pick_coords(coord)
        counts = self.radar_data.data[trace, sample]
        return "trace=%d sample=%d (%d counts)" % (trace, sample, counts)


class ExperimentalRadarWindow(BasicRadarWindow):
    def __init__(
        self,
        transect: str,
        filename: Optional[str] = None,
        parent=None,  # type: Optional[Any]
        parent_xlim_changed_cb=None,  # type: Optional[Callable[List[float]]]
        parent_cursor_cb=None,  # type: Optional[Callable[float]]
        close_cb=None,  # type: Optional[Callable[None]]
    ):
        # type: (...) -> None
        """
        TODO
        """
        super(ExperimentalRadarWindow, self).__init__(
            transect,
            filename,
            parent,
            parent_xlim_changed_cb,
            parent_cursor_cb,
            close_cb,
        )
        # TODO: do we care about gps_start, gps_end?
        # They would be used to allow interpolating from traces to linear time,
        # where the time bounds were from the data in targ/xtra/ALL/deva/psts.
        # Usage would be transect_data.rtc.set_linear_bounds(gps_start, gps_end),
        # and then if posix fails, return linear when either of the parent
        # positioning callbacks is called.
        # NB - for now, a hack in conversions.py means that it loads
        # time/positions from deva/psts, so there's no need to pass 'em in here.

    def create_layout(
        self, plot_params: PlotParams, plot_config: PlotConfig
    ) -> PlotObjects:
        """
        TODO
        """
        plot_objects = super(ExperimentalRadarWindow, self).create_layout(
            plot_params, plot_config
        )

        print("called add_experimental_layout")

        major_color = self.plot_config.cmap_major_colors[self.plot_params.cmap]
        minor_color = self.plot_config.cmap_minor_colors[self.plot_params.cmap]

        plot_objects.vert_scale = scalebar.Scalebar(
            plot_objects.radar_ax,
            0,
            0,
            0,
            0.01,
            fontsize=24,
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
            fontsize=24,
            majorcolor="r",
            barstyle="simple",
            coords="frac",
            orientation="horiz",
            linewidth=4,
            unit_label="km",
            autoupdate=False,
        )

        plot_objects.annotations_vbox.addWidget(plot_objects.crossover_checkbox)

        ######
        ##########
        # Tab for various analysis experiments

        # And, all of the inputs for configuring scale bars
        plot_objects.vert_scale_checkbox = QtWidgets.QCheckBox("Vertical Scale")
        plot_objects.vert_scale_checkbox.clicked.connect(
            self._on_vert_scale_checkbox_changed,
        )
        plot_objects.vert_scale_length_label = QtWidgets.QLabel("Length: (m)")
        plot_objects.vert_scale_length_textbox = QtWidgets.QLineEdit()
        plot_objects.vert_scale_length_textbox.editingFinished.connect(
            self._on_vert_scale_length_textbox_edited,
        )
        plot_objects.vert_scale_length_textbox.setText(
            "%0.2f" % plot_params.vert_scale_length
        )
        plot_objects.vert_scale_length_textbox.setMinimumWidth(100)
        plot_objects.vert_scale_length_textbox.setMaximumWidth(120)
        plot_objects.vert_scale_origin_label = QtWidgets.QLabel(
            "origin (x, y) (fraction):"
        )
        plot_objects.vert_scale_x0_textbox = QtWidgets.QLineEdit()
        plot_objects.vert_scale_x0_textbox.editingFinished.connect(
            self._on_vert_scale_x0_textbox_edited,
        )
        plot_objects.vert_scale_x0_textbox.setText("%0.2f" % plot_params.vert_scale_x0)
        plot_objects.vert_scale_x0_textbox.setMinimumWidth(60)
        plot_objects.vert_scale_x0_textbox.setMaximumWidth(80)
        plot_objects.vert_scale_y0_textbox = QtWidgets.QLineEdit()
        plot_objects.vert_scale_y0_textbox.editingFinished.connect(
            self._on_vert_scale_y0_textbox_edited,
        )
        plot_objects.vert_scale_y0_textbox.setText("%0.2f" % plot_params.vert_scale_y0)
        plot_objects.vert_scale_y0_textbox.setMinimumWidth(60)
        plot_objects.vert_scale_y0_textbox.setMaximumWidth(80)

        plot_objects.horiz_scale_checkbox = QtWidgets.QCheckBox("Horizontal Scale")
        plot_objects.horiz_scale_checkbox.clicked.connect(
            self._on_horiz_scale_checkbox_changed,
        )
        plot_objects.horiz_scale_length_label = QtWidgets.QLabel("Length: (km)")
        plot_objects.horiz_scale_length_textbox = QtWidgets.QLineEdit()
        plot_objects.horiz_scale_length_textbox.editingFinished.connect(
            self._on_horiz_scale_length_textbox_edited,
        )
        plot_objects.horiz_scale_length_textbox.setText(
            "%0.2f" % plot_params.horiz_scale_length
        )
        plot_objects.horiz_scale_length_textbox.setMinimumWidth(100)
        plot_objects.horiz_scale_length_textbox.setMaximumWidth(120)

        plot_objects.horiz_scale_origin_label = QtWidgets.QLabel(
            "origin (x, y) (fraction):"
        )
        plot_objects.horiz_scale_x0_textbox = QtWidgets.QLineEdit()
        plot_objects.horiz_scale_x0_textbox.editingFinished.connect(
            self._on_horiz_scale_x0_textbox_edited,
        )
        plot_objects.horiz_scale_x0_textbox.setText(
            "%0.2f" % plot_params.horiz_scale_x0
        )
        plot_objects.horiz_scale_x0_textbox.setMinimumWidth(60)
        plot_objects.horiz_scale_x0_textbox.setMaximumWidth(80)
        plot_objects.horiz_scale_y0_textbox = QtWidgets.QLineEdit()
        plot_objects.horiz_scale_y0_textbox.editingFinished.connect(
            self._on_horiz_scale_y0_textbox_edited,
        )
        plot_objects.horiz_scale_y0_textbox.setText(
            "%0.2f" % plot_params.horiz_scale_y0
        )
        plot_objects.horiz_scale_y0_textbox.setMinimumWidth(60)
        plot_objects.horiz_scale_y0_textbox.setMaximumWidth(80)

        vert_scale_length_hbox = QtWidgets.QHBoxLayout()
        vert_scale_pos_hbox = QtWidgets.QHBoxLayout()
        vert_scale_length_hbox.addWidget(plot_objects.vert_scale_checkbox)
        vert_scale_length_hbox.addStretch(1)
        vert_scale_length_hbox.addWidget(plot_objects.vert_scale_length_label)
        vert_scale_length_hbox.addWidget(plot_objects.vert_scale_length_textbox)
        vert_scale_pos_hbox.addStretch(1)
        vert_scale_pos_hbox.addWidget(plot_objects.vert_scale_origin_label)
        vert_scale_pos_hbox.addWidget(plot_objects.vert_scale_x0_textbox)
        vert_scale_pos_hbox.addWidget(plot_objects.vert_scale_y0_textbox)
        vert_scale_vbox = QtWidgets.QVBoxLayout()
        vert_scale_vbox.addLayout(vert_scale_length_hbox)
        vert_scale_vbox.addLayout(vert_scale_pos_hbox)

        horiz_scale_length_hbox = QtWidgets.QHBoxLayout()
        horiz_scale_pos_hbox = QtWidgets.QHBoxLayout()
        horiz_scale_length_hbox.addWidget(plot_objects.horiz_scale_checkbox)
        horiz_scale_length_hbox.addStretch(1)
        horiz_scale_length_hbox.addWidget(plot_objects.horiz_scale_length_label)
        horiz_scale_length_hbox.addWidget(plot_objects.horiz_scale_length_textbox)
        horiz_scale_pos_hbox.addStretch(1)
        horiz_scale_pos_hbox.addWidget(plot_objects.horiz_scale_origin_label)
        horiz_scale_pos_hbox.addWidget(plot_objects.horiz_scale_x0_textbox)
        horiz_scale_pos_hbox.addWidget(plot_objects.horiz_scale_y0_textbox)
        horiz_scale_vbox = QtWidgets.QVBoxLayout()
        horiz_scale_vbox.addLayout(horiz_scale_length_hbox)
        horiz_scale_vbox.addLayout(horiz_scale_pos_hbox)

        scale_vbox = QtWidgets.QVBoxLayout()
        scale_vbox.addLayout(vert_scale_vbox)
        scale_vbox.addLayout(horiz_scale_vbox)
        scale_vbox.addStretch(1)

        scale_widget = QtWidgets.QWidget()
        scale_widget.setLayout(scale_vbox)

        plot_objects.tabs.addTab(scale_widget, "Scale Bars")

        return plot_objects

    def data_blit(self) -> None:
        """
        TODO
        """
        # NOTE: This purposely does NOT extend BasicRadarWindow.data_blit,
        # because there's an ordering issue.
        """
        This redraws all the various rcoeff/pick/etc plots, but not the
        radar background.
        # TODO: I haven't tested  whether it would be faster to do it like
        # this or do a per-artist blit when it changes. However, this seems
        # easier/cleaner.
        """
        self.plot_objects.canvas.restore_region(self.radar_restore)

        # These need to happen before set_visible because they may detect
        # bad parameters and set the flag accordingly
        self.maybe_update_rcoeff()
        self.maybe_update_simple_rcoeff()
        self.maybe_update_multiple()  # this looks at flag to decide whether to recalc

        self.data_set_visible(self.plot_objects, self.plot_params)
        # TODO: If this series starts getting too slow, move the "set_data"
        # logic back to the callbacks that change it. However, there are
        # enough things that change the picks/max values that it's a lot
        # simpler to put all of that right here.

        # All of these set the data and call draw_artist, regardless of whether
        # it's visible or not.
        self.plot_curr_picks()
        self.plot_computed_horizons()

        self.plot_rcoeff()
        self.plot_simple_rcoeff()

        self.plot_objects.radar_ax.draw_artist(self.plot_objects.multiple_line)

        self.plot_scalebars()

        self.plot_objects.canvas.update()

        self.data_restore = self.plot_objects.canvas.copy_from_bbox(
            self.plot_objects.full_ax.bbox
        )

        self.cursor_blit()

    def data_set_invisible(self, plot_objects: PlotObjects) -> None:
        """
        Set ALL overlays invisible.
        """
        super(ExperimentalRadarWindow, self).data_set_invisible(plot_objects)
        plot_objects.vert_scale.set_visible(False)
        plot_objects.horiz_scale.set_visible(False)

    def data_set_visible(
        self, plot_objects: PlotObjects, plot_params: PlotParams
    ) -> None:
        """
        Replot various data overlays based on configuration in plot_params.
        Does NOT turn everything on; only those that are enabled.
        """
        super(ExperimentalRadarWindow, self).data_set_visible(plot_objects, plot_params)
        plot_objects.vert_scale.set_visible(plot_params.vert_scale_visible)
        plot_objects.horiz_scale.set_visible(plot_params.horiz_scale_visible)

    def plot_scalebars(self) -> None:
        """
        TODO
        """
        xlim = self.plot_objects.radar_ax.get_xlim()
        dist0 = self.transect_data.rpc.along_track_dist([0, xlim[0]], "traces")
        dist1 = self.transect_data.rpc.along_track_dist([0, xlim[1]], "traces")
        data_width = dist1 - dist0  # in meters

        ylim = self.plot_objects.radar_ax.get_ylim()
        data_height = np.abs(ylim[1] - ylim[0]) * 1.69  # in meters

        self.plot_objects.vert_scale.set_length(
            self.plot_params.vert_scale_length, data_height
        )
        self.plot_objects.vert_scale.set_origin(
            self.plot_params.vert_scale_x0, self.plot_params.vert_scale_y0
        )
        self.plot_objects.vert_scale.update()

        self.plot_objects.horiz_scale.set_length(
            self.plot_params.horiz_scale_length, (data_width / 1000.0)
        )
        self.plot_objects.horiz_scale.set_origin(
            self.plot_params.horiz_scale_x0, self.plot_params.horiz_scale_y0
        )
        self.plot_objects.horiz_scale.update()

        for element in self.plot_objects.vert_scale.elements.values():
            self.plot_objects.radar_ax.draw_artist(element)
        for element in self.plot_objects.horiz_scale.elements.values():
            self.plot_objects.radar_ax.draw_artist(element)

    def _on_vert_scale_checkbox_changed(self) -> None:
        """
        TODO
        """
        checked = self.plot_objects.vert_scale_checkbox.isChecked()
        self.plot_params.vert_scale_visible = checked
        # TODO: This may call setChecked(False), which seems to disable the
        # callback the next time around ... but it works again on the 2nd click.
        self.data_blit()

    def _on_vert_scale_length_textbox_edited(self) -> None:
        """
        Update plot_objects with new length and redraw, after sanity checking.
        """
        curr_length_str = "%r" % self.plot_params.vert_scale_length
        try:
            length = float(self.plot_objects.vert_scale_length_textbox.text())
        except ValueError:
            msg = "Please enter numerical value for length"
            show_error_message_box(msg)
            self.plot_objects.vert_scale_length_textbox.setText(curr_length_str)
            return

        if length <= 0:
            msg = "Please enter positive length"
            show_error_message_box(msg)
            self.plot_objects.vert_scale_length_textbox.setText(curr_length_str)
            return

        if length != self.plot_params.vert_scale_length:
            self.plot_params.vert_scale_length = length
            self.data_blit()

    def _on_vert_scale_x0_textbox_edited(self) -> None:
        """
        Update plot_objects with new x0 and redraw
        """
        curr_x0_str = "%r" % self.plot_params.vert_scale_x0
        try:
            x0 = float(self.plot_objects.vert_scale_x0_textbox.text())
        except ValueError:
            msg = "Please enter numerical value for x0"
            show_error_message_box(msg)
            self.plot_objects.vert_scale_x0_textbox.setText(curr_x0_str)
            return

        if x0 < 0.0 or x0 > 1.0:
            msg = "Please enter x0 in range [0, 1]"
            show_error_message_box(msg)
            self.plot_objects.vert_scale_x0_textbox.setText(curr_x0_str)
            return

        if x0 != self.plot_params.vert_scale_x0:
            self.plot_params.vert_scale_x0 = x0
            self.data_blit()

    def _on_vert_scale_y0_textbox_edited(self) -> None:
        """
        Update plot_objects with new y0 and redraw
        """
        curr_y0_str = "%r" % self.plot_params.vert_scale_y0
        try:
            y0 = float(self.plot_objects.vert_scale_y0_textbox.text())
        except ValueError:
            msg = "Please enter numerical value for y0"
            show_error_message_box(msg)
            self.plot_objects.vert_scale_y0_textbox.setText(curr_y0_str)
            return

        if y0 < 0.0 or y0 > 1.0:
            msg = "Please enter y0 in range [0, 1]"
            show_error_message_box(msg)
            self.plot_objects.vert_scale_y0_textbox.setText(curr_y0_str)
            return

        if y0 != self.plot_params.vert_scale_y0:
            self.plot_params.vert_scale_y0 = y0
            self.data_blit()

    def _on_horiz_scale_checkbox_changed(self) -> None:
        """
        TODO
        """
        checked = self.plot_objects.horiz_scale_checkbox.isChecked()
        self.plot_params.horiz_scale_visible = checked
        # TODO: This may call setChecked(False), which seems to disable the
        # callback the next time around ... but it works again on the 2nd click.
        self.data_blit()

    def _on_horiz_scale_length_textbox_edited(self) -> None:
        """
        Update plot_objects with new length and redraw, after sanity checking.
        """
        curr_length_str = "%r" % self.plot_params.horiz_scale_length
        try:
            length = float(self.plot_objects.horiz_scale_length_textbox.text())
        except ValueError:
            msg = "Please enter numerical value for length"
            show_error_message_box(msg)
            self.plot_objects.horiz_scale_length_textbox.setText(curr_length_str)
            return

        if length <= 0:
            msg = "Please enter positive length"
            show_error_message_box(msg)
            self.plot_objects.horiz_scale_length_textbox.setText(curr_length_str)
            return

        if length != self.plot_params.horiz_scale_length:
            self.plot_params.horiz_scale_length = length
            self.data_blit()

    # This is crying out for a lambda taking the textbox object and the var it
    # goes into ...
    def _on_horiz_scale_x0_textbox_edited(self) -> None:
        """
        Update plot_objects with new x0 and redraw
        """
        curr_x0_str = "%r" % self.plot_params.horiz_scale_x0
        try:
            x0 = float(self.plot_objects.horiz_scale_x0_textbox.text())
        except ValueError:
            msg = "Please enter numerical value for x0"
            show_error_message_box(msg)
            self.plot_objects.horiz_scale_x0_textbox.setText(curr_x0_str)
            return

        if x0 < 0.0 or x0 > 1.0:
            msg = "Please enter x0 in range [0, 1]"
            show_error_message_box(msg)
            self.plot_objects.horiz_scale_x0_textbox.setText(curr_x0_str)
            return

        if x0 != self.plot_params.horiz_scale_x0:
            self.plot_params.horiz_scale_x0 = x0
            self.data_blit()

    def _on_horiz_scale_y0_textbox_edited(self) -> None:
        """
        Update plot_objects with new y0 and redraw
        """
        curr_y0_str = "%r" % self.plot_params.horiz_scale_y0
        try:
            y0 = float(self.plot_objects.horiz_scale_y0_textbox.text())
        except ValueError:
            msg = "Please enter numerical value for y0"
            show_error_message_box(msg)
            self.plot_objects.horiz_scale_y0_textbox.setText(curr_y0_str)
            return

        if y0 < 0.0 or y0 > 1.0:
            msg = "Please enter y0 in range [0, 1]"
            show_error_message_box(msg)
            self.plot_objects.horiz_scale_y0_textbox.setText(curr_y0_str)
            return

        if y0 != self.plot_params.horiz_scale_y0:
            self.plot_params.horiz_scale_y0 = y0
            self.data_blit()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    parser = argparse.ArgumentParser(
        description="RadarFigure - interface for viewing radar data"
    )
    # Both provider and campaign are required to determine file type.
    # TODO: Consider switching this to an enum of supported formats.
    parser.add_argument("provider", help="Institution that collected the data")
    parser.add_argument("campaign", help="Campaign")
    parser.add_argument("filepath", help="Full path to the datafile")
    parser.add_argument("transect", help="Name of transect")
    parser.add_argument(
        "--experimental",
        action="store_true",
        help="Whether to use experimental version of GUI",
    )
    args = parser.parse_args()

    if args.experimental:
        radar_window = ExperimentalRadarWindow(
            args.provider, args.campaign, args.filepath, args.transect
        )
    else:
        radar_window = BasicRadarWindow(
            args.provider, args.campaign, args.filepath, args.transect
        )

    radar_window.show()
    app.exec_()
