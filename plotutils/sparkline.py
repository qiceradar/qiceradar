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


from typing import Dict, List, Optional, Tuple

import matplotlib
import numpy as np


# TODO: Should this behave more like an artist?
class Sparkline(object):
    # NB - NONE of these functions actually call draw on the axis.
    def __init__(
        self,
        ax: matplotlib.axes.Axes,
        scalebar_pos: Optional[Tuple[float, float]] = None,
        scalebar_len: Optional[float] = None,
        major_color: str = "r",
        minor_color: str = "o",
        units: str = "",
        plot_width: Optional[float] = None,
        plot_offset: Optional[float] = None,
        data_axis: str = "x",
        show_extrema: bool = True,
    ) -> None:
        """
        Draws a sparkline on the input axes. Input data will be registered
        to either the x or y axis.

        Params:
        * scalebar_pos [x,y] - fractional postion for the scalebar.
            If None, no bar drawn.
        * scalebar_len - desired scalebar length
        * minor_color - color for dots at min/max
        * major_color - color for everything else
        * units (str) - used when labeling the scalebars
        * plot_width - If None, values are used directly. Otherwise, this
           specifies the fraction of the total plot width/height to be used.
        * plot_offset - only used if plot_width is not None. How far along
            axis to offset the sparkline.
        * data_axis - which axis matches the data, and which is not
            modified by plot_width.
        * show_extrema - whether to display larger dots + value of min/max points
        """
        if plot_width is not None and plot_offset is None:
            msg = "Relative width requires offset parameter!"
            raise Exception(msg)
        if scalebar_pos is not None and scalebar_len is None:
            msg = "If position specified for scalebar, length is also required"
            raise Exception(msg)

        self.ax = ax
        self.scalebar_pos = scalebar_pos
        self.scalebar_len = scalebar_len
        self.units = units
        self.plot_width = plot_width
        self.plot_offset = plot_offset
        self.data_axis = data_axis
        self.show_extrema = show_extrema
        # This is ugly - sometimes I want to give an absolute offset (for
        # traces), sometimes I want relative (for unrelated data)
        self.abs_offset: Optional[float] = None

        # Vectors that are going to be plotted.
        self.x_in: Optional[List[float]] = None
        self.y_in: Optional[List[float]] = None

        # Will hold all created artists
        self.elements: Dict[str, matplotlib.lines.Line2D] = {}

        self.plot(major_color, minor_color)

        self.ax.callbacks.connect("xlim_changed", self.update)
        self.ax.callbacks.connect("ylim_changed", self.update)

    def plot(self, major_color: str, minor_color: str) -> None:
        """
        Performs initial creation of the plot elements.
        """
        (self.elements["line"],) = self.ax.plot(
            0, 0, ".", color=major_color, markersize=0.25
        )
        (self.elements["scale"],) = self.ax.plot(
            0, 0, color=major_color, linestyle="-", linewidth=5
        )
        self.elements["scale_text"] = self.ax.text(0, 0, "", color=major_color)
        (self.elements["min_pt"],) = self.ax.plot(
            0, 0, ".", color=minor_color, markersize=8
        )
        (self.elements["max_pt"],) = self.ax.plot(
            0, 0, ".", color=minor_color, markersize=8
        )
        self.elements["min_text"] = self.ax.text(0, 0, "", color=major_color)
        self.elements["max_text"] = self.ax.text(0, 0, "", color=major_color)

        self.set_visible(False)

    def set_data(
        self, x_in: List[float], y_in: List[float], offset: Optional[float] = None
    ) -> None:
        """
        For now, we're assuming that we're plotting data vs. the x-axis.
        (Like for the RCoeff sparkline, NOT the trace one.)
        * offset - replacement for the static offset .. needed for the
           interactively updating position that follows the cursor around.
        """
        # Cache these for the later update steps ...
        self.x_in = x_in
        self.y_in = y_in
        if offset is not None:
            self.abs_offset = offset

        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        xmin = np.min(xlim)
        xmax = np.max(xlim)
        ymin = np.min(ylim)
        ymax = np.max(ylim)

        dx = xlim[1] - xlim[0]
        dy = ylim[1] - ylim[0]

        if self.data_axis == "x":
            x_plot = x_in
            if self.plot_width is None or len(y_in) == 1:
                min_data = np.min(y_in)
                max_data = np.max(y_in)
                y_plot = y_in
                # How much to scale plot values by to make 'em fit.
                data_range = max(1, max_data - min_data)
                vert_scale = self.plot_width * np.abs(dy)
                data_scale = 1.0 * vert_scale / data_range
            else:
                y_cropped = [
                    yy for (xx, yy) in zip(x_in, y_in) if xx <= xmax and xx >= xmin
                ]
                min_data = np.min(y_cropped)
                max_data = np.max(y_cropped)
                # avoid divide-by-zero in case of length-1 data
                data_range = max(1, max_data - min_data)
                vert_scale = self.plot_width * np.abs(dy)
                data_scale = 1.0 * vert_scale / data_range
                if self.abs_offset is None:
                    y_offset = ymin + self.plot_offset * np.abs(dy)
                else:
                    y_offset = self.abs_offset
                y_plot = y_offset + (y_in - min_data) * data_scale * np.sign(dy)
            max_data_idx = np.where(y_in == max_data)[0]
            min_data_idx = np.where(y_in == min_data)[0]

        elif self.data_axis == "y":
            y_plot = y_in
            if self.plot_width is None or len(x_in) == 1:
                min_data = np.min(x_in)
                max_data = np.max(x_in)
                x_plot = x_in
                data_range = max(1, max_data - min_data)
                vert_scale = self.plot_width * np.abs(dx)
                data_scale = 1.0 * vert_scale / data_range
            else:
                x_cropped = [
                    xx for (xx, yy) in zip(x_in, y_in) if yy <= ymax and yy >= ymin
                ]
                min_data = np.min(x_cropped)
                max_data = np.max(x_cropped)
                # avoid divide-by-zero in case of length-1 data
                data_range = max(1, max_data - min_data)
                vert_scale = self.plot_width * np.abs(dx)
                data_scale = 1.0 * vert_scale / data_range
                if self.abs_offset is None:
                    x_offset = xmin + self.plot_offset * np.abs(dx)
                else:
                    x_offset = self.abs_offset
                x_plot = x_offset + (x_in - min_data) * data_scale * np.sign(dx)

            max_data_idx = np.where(x_in == max_data)[0]
            min_data_idx = np.where(x_in == min_data)[0]

        self.elements["line"].set_data(x_plot, y_plot)

        # Attempt at sparkline-style scale
        # (limiting the available indices to those that are presently displayed)
        if self.show_extrema:
            self.elements["min_pt"].set_data(
                x_plot[min_data_idx[0]], y_plot[min_data_idx[0]]
            )
            self.elements["max_pt"].set_data(
                x_plot[max_data_idx[0]], y_plot[max_data_idx[0]]
            )

            self.elements["min_text"].set_text(
                "%0.1f %s" % (x_in[min_data_idx[0]], self.units)
            )
            self.elements["max_text"].set_text(
                "%0.1f %s" % (x_in[max_data_idx[0]], self.units)
            )

            if self.data_axis == "x":
                self.elements["min_text"].set_position(
                    [x_plot[min_data_idx[0]], y_plot[min_data_idx[0]]] - 0.03 * dy
                )
                self.elements["max_text"].set_position(
                    [
                        x_plot[max_data_idx[0]],
                        y_plot[max_data_idx[0]] + 0.01 * dy,
                    ]
                )
                self.elements["min_text"].set_text(
                    "%0.1f %s" % (y_in[min_data_idx[0]], self.units)
                )
                self.elements["max_text"].set_text(
                    "%0.1f %s" % (y_in[max_data_idx[0]], self.units)
                )

            elif self.data_axis == "y":
                self.elements["min_text"].set_position(
                    [
                        x_plot[min_data_idx[0]] + 0.01 * dx,
                        y_plot[min_data_idx[0]],
                    ]
                )
                self.elements["max_text"].set_position(
                    [
                        x_plot[max_data_idx[0]] + 0.01 * dx,
                        y_plot[max_data_idx[0]],
                    ]
                )
                self.elements["min_text"].set_text(
                    "%0.1f %s" % (x_in[min_data_idx[0]], self.units)
                )
                self.elements["max_text"].set_text(
                    "%0.1f %s" % (x_in[max_data_idx[0]], self.units)
                )

        # The old scale bar that DAY didn't like
        if self.scalebar_pos is not None:
            scale_x = xmin + self.scalebar_pos[0] * abs(dx)
            scale_y = ymin + self.scalebar_pos[1] * abs(dy)
            self.elements["scale_text"].set_text(
                "%r %s" % (self.scalebar_len, self.units)
            )
            if self.data_axis == "x":
                self.elements["scale"].set_data(
                    [scale_x, scale_x],
                    [scale_y, scale_y + self.scalebar_len * data_scale * np.sign(dy)],
                )
                self.elements["scale_text"].set_position(
                    [
                        scale_x + 0.015 * dx,
                        scale_y + 0.25 * self.scalebar_len * data_scale * np.sign(dy),
                    ]
                )
            elif self.data_axis == "y":
                self.elements["scale"].set_data(
                    [scale_x, scale_x + self.scalebar_len * data_scale * np.sign(dx)],
                    [scale_y, scale_y],
                )
                self.elements["scale_text"].set_position(
                    [
                        scale_x,
                        scale_y + 0.015 * dy,
                    ]
                )

    def set_major_color(self, color: str) -> None:
        """
        Changes color used in this sparkline.
        Useful for when the colormap changes interactively.
        """
        for key in ["line", "min_text", "max_text", "scale", "scale_text"]:
            self.elements[key].set_color(color)

    def set_minor_color(self, color: str) -> None:
        for key in ["min_pt", "max_pt"]:
            self.elements[key].set_color(color)

    def set_visible(self, visible: bool) -> None:
        """
        Sets the sparkline to be visible or not.
        (Lets my GUI turn this on/off as a unit.)
        """
        for elem in self.elements.values():
            elem.set_visible(visible)

    def update(self, _=None) -> None:
        """
        Called when the axis bounds change.
        Yeah, this is hacky, but there would have been a ton of repeated
        code anyways, and I don't think this is a performance bottleneck.
        """
        # reposition scalebar
        # move the spark dots to w/in the FOV
        # rescale the sparkline
        if self.x_in is not None and self.y_in is not None:
            self.set_data(self.x_in, self.y_in)
