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

from typing import Dict, Optional, Tuple

import matplotlib
import matplotlib.patches
import matplotlib.transforms
import numpy as np


class Scalebar(object):
    # NB - NONE of these functions actually call draw on the axis.
    def __init__(
        self,
        ax: matplotlib.axes.Axes,
        x0: float,
        y0: float,
        length: float,
        width: float,
        coords: str = "frac",
        orientation: str = "horiz",
        barstyle: str = "simple",
        unit_label: Optional[str] = None,
        unit_factor: float = 1,
        fontsize: float = 9,
        fontcolor: str = "k",
        zorder: float = 10,
        majorcolor: str = "k",
        minorcolor: str = "w",
        linewidth: int = 1,
        autoupdate: bool = True,
        alpha: float = 0.0,
    ) -> None:
        """
        Adds a scalebar to specified axes.

        I chose to reimplement my own because I can't use basemap (due to its
            poor handling of ps71) and because I want it to be more automatic
            (since I'm using it in an interactively resized plot.) I'd also
            like to be able to use it in non-map plots. (Thus the separation
            of unit name and factor.)

        TODO: The scalebar only handles distance increments that are greater
            than one. Clean it up to allow nice printing of whatever data type.
            This is OK for now if I'm just working in PS71.
        TODO: Add warning message for trying to set unit_factor when coords
            are 'frac'?
        TODO: current abs/frac/unit_factor nomenclature is confusing. Maybe
            data/frac/unit_factor?
        NB: I saw the AnchoredSizeBar in mpl_toolkits...maybe this should
            derive from that, rather than be written from scratch.

        Parameters:
        * ax - the axis on which to draw
        * barstyle - ('simple'|'fancy') an attempt to match GMT's options.
          (and copied from matplotlib.basemap)
        * coords - ('abs'|'frac') whether the input coordinates are absolute
            or fractional positioning within the axis ('frac').
        * orientation - ('vert'|'horiz') whether it is vertical or horizontal
        * x0, y0 - position of lower or left edge of scalebar.
        * length, width - length/width of scalebar. (Length is always in the
           direction of units being measured; width is how thick bar is.)
           Does not include the label.
           if coords='frac', this will give the shape of the bar.
           if coords='abs', length should be desired length in plot units.
           width is always in fraction of yaxis range.
        * unit_label, unit_factor - What units to label the scale bar with, and
           how to convert from axis units to scale units. (For or a scalebar
           with label='km' plotted on ax with units 'm', factor=1000)
        * majorcolor - color for text, ticks, and scalebar.
        * minorcolor - alternating color for fancy scalebar. If None, those
           rectangles won't be filled in.
        * autoupdate - whether to hook update() in to the xlim_changed signals
        * alpha - alpha for the background
        """
        print(
            f"Initializing Scalebar. x0,y0 = {x0}, {y0}. length,width = {length}, {width}. unit_factor={unit_factor}"
        )
        self.ax = ax
        self.x0 = x0
        self.y0 = y0
        self.length = length
        self.width = width
        self.coords = coords
        self.orientation = orientation
        self.barstyle = barstyle
        self.unit_label = unit_label
        self.unit_factor = unit_factor
        self.fontsize = fontsize
        self.zorder = zorder
        #        self.ax.set_zorder(self.zorder) # Gotta set it here to be in front of the background
        self.majorcolor = majorcolor
        self.minorcolor = minorcolor
        self.linewidth = linewidth
        self.autoupdate = autoupdate
        self.alpha = alpha
        # Will hold all the created artists
        self.elements: Dict[str, matplotlib.lines.Line2D] = {}
        # Create ax for background; needs to be smaller zorder than the axis itself.
        # QUESTION: Does zorder for an axis bg compare to other axes, or to the
        #           zorder of elements within those axes?
        fig = self.ax.get_figure()
        self.background = matplotlib.patches.Rectangle(
            [0, 0],
            0,
            0,
            facecolor=[1, 1, 1, self.alpha],
            edgecolor="none",
            zorder=self.zorder - 1,
            transform=fig.transFigure,
        )
        self.ax.add_patch(self.background)

        # This is super-hacky, since setup seems to change bounds around...
        if self.barstyle == "simple":
            self._setup_simple()
        elif self.barstyle == "fancy":
            self._setup_fancy()
        else:
            msg = "Invalid option %r for style." % (self.barstyle)
            raise KeyError(msg)

        if self.autoupdate:
            update_lambda = lambda x: self.update()
            self.ax.callbacks.connect("xlim_changed", update_lambda)
            self.ax.callbacks.connect("ylim_changed", update_lambda)

    def __repr__(self):
        repr = (
            "Scalebar(x0=%r, y0=%r, length=%r, width=%r, coords=%r, "
            "orientation=%r, barstyle=%r, unit_label=%r, unit_factor=%r, "
            "fontsize=%r, zorder=%r, majorcolor=%r, minorcolor=%r, "
            "linewidth=%r, autoupdate=%r)"
            % (
                self.x0,
                self.y0,
                self.length,
                self.width,
                self.coords,
                self.orientation,
                self.barstyle,
                self.unit_label,
                self.unit_factor,
                self.fontsize,
                self.zorder,
                self.majorcolor,
                self.minorcolor,
                self.linewidth,
                self.autoupdate,
            )
        )
        return repr

    def get_full_extent(self, pad: float = 0.0) -> Tuple[float, float, float, float]:
        """
        return the extent, in figure coords, of all elements in the scalebar.
        """
        # Gotta draw it once just to know where everythign is :-\
        self.ax.figure.canvas.draw()

        # NB: matplotlib.lines.Line2D has a required "renderer" argument, while
        # it's optional for matplotlib.text.Text and matplotlib.patches.Polygon
        extents = [elem.get_window_extent(None) for elem in self.elements.values()]

        bbox = matplotlib.transforms.Bbox.union(extents)
        bbox_exp = bbox.expanded(1.0 + pad, 1.0 + pad)
        fig = self.ax.get_figure()
        extent = bbox_exp.transformed(fig.transFigure.inverted())
        return extent

    def set_visible(self, visible: bool) -> None:
        """
        Sets the scalebar to be visible or not.
        (Lets it be tured on/off as a unit by a GUI.)
        """
        for elem in self.elements.values():
            elem.set_visible(visible)

    def set_origin(
        self, x0: Optional[float] = None, y0: Optional[float] = None
    ) -> None:
        """Set scalebar origin"""
        if x0 is not None:
            self.x0 = x0
        if y0 is not None:
            self.y0 = y0

    def set_length(self, length: float, scale: Optional[float] = None) -> None:
        """
        Set scalebar length. If scale is set, it gives total dimensions of
        current axes in length's direction and units.
        """
        xlim = self.ax.get_xlim()
        dx = xlim[1] - xlim[0]

        ylim = self.ax.get_ylim()
        dy = ylim[1] - ylim[0]

        if scale is None:
            self.length = length
            return
        if self.coords == "frac":
            self.length = length / scale
        elif self.coords == "abs":
            self.length = length
        else:
            raise Exception("Invalid coordinate type")

        if self.orientation == "horiz":
            self.unit_factor = dx / scale
            # print("set_length()...length: %0.2f, scale: %0.2f, dx: %d" % (length, scale, dx))
        elif self.orientation == "vert":
            self.unit_factor = dy / scale
            # print("set_length(): %0.2f, scale: %0.2f, dy: %d" % (length, scale, dy))
        else:
            raise Exception("Invalid orientation")

    def update(self) -> None:
        """
        Call this when the axis bounds change.
        """
        if self.barstyle == "simple":
            self._update_simple()
        elif self.barstyle == "fancy":
            self._update_fancy()
        else:
            msg = "Invalid option %r for style." % (self.barstyle)
            raise KeyError(msg)
        # update the background ... this operation can be slow, so only
        # do it if background is meant to be visible.
        if self.alpha > 0:
            ext = self.get_full_extent(pad=0.01)
            self.background.set_bounds(*ext.bounds)

    def _setup_simple(self) -> None:
        """
        Setup the plot objects for a simple line, with ticks at the ends.
        """
        if self.orientation == "horiz":
            (self.elements["line"],) = self.ax.plot(
                [0, 0],
                [0, 0],
                color=self.majorcolor,
                zorder=self.zorder,
                linewidth=self.linewidth,
            )
            (self.elements["tick1"],) = self.ax.plot(
                [0, 0],
                [0, 0],
                color=self.majorcolor,
                zorder=self.zorder,
                linewidth=self.linewidth,
            )
            (self.elements["tick2"],) = self.ax.plot(
                [0, 0],
                [0, 0],
                color=self.majorcolor,
                zorder=self.zorder,
                linewidth=self.linewidth,
            )
            self.elements["label"] = self.ax.text(
                0,
                0,
                "0",
                weight="bold",
                horizontalalignment="center",
                verticalalignment="bottom",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )
        elif self.orientation == "vert":
            (self.elements["line"],) = self.ax.plot(
                [0, 0],
                [0, 0],
                color=self.majorcolor,
                zorder=self.zorder,
                linewidth=self.linewidth,
            )
            (self.elements["tick1"],) = self.ax.plot(
                [0, 0],
                [0, 0],
                color=self.majorcolor,
                zorder=self.zorder,
                linewidth=self.linewidth,
            )
            (self.elements["tick2"],) = self.ax.plot(
                [0, 0],
                [0, 0],
                color=self.majorcolor,
                zorder=self.zorder,
                linewidth=self.linewidth,
            )
            self.elements["label"] = self.ax.text(
                0,
                0,
                "0",
                weight="bold",
                horizontalalignment="left",
                verticalalignment="center",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )
        else:
            raise Exception("Invalid orientation")

    def _setup_fancy(self) -> None:
        """
        Set up all the plot objects for plotting 4 alternating-color blocks,
        with the ends and midpoint labeled below or left,
        and units labeled above or right.
        NB: Just sets up the objects; _update_fancy() makes them make sense.
        """
        # text alignment settings depend on horizontal/vertical
        if self.orientation == "horiz":
            self.elements["title"] = self.ax.text(
                0,
                0,
                self.unit_label,
                horizontalalignment="center",
                verticalalignment="bottom",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

            self.elements["tick1_text"] = self.ax.text(
                0,
                0,
                "0",
                horizontalalignment="center",
                verticalalignment="top",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

            self.elements["tick3_text"] = self.ax.text(
                0,
                0,
                "0",
                horizontalalignment="center",
                verticalalignment="top",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

            self.elements["tick5_text"] = self.ax.text(
                0,
                0,
                "0",
                horizontalalignment="center",
                verticalalignment="top",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

        elif self.orientation == "vert":
            self.elements["title"] = self.ax.text(
                0,
                0,
                self.unit_label,
                horizontalalignment="left",
                verticalalignment="center",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

            self.elements["tick1_text"] = self.ax.text(
                0,
                0,
                "0",
                horizontalalignment="right",
                verticalalignment="center",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

            self.elements["tick3_text"] = self.ax.text(
                0,
                0,
                "0",
                horizontalalignment="right",
                verticalalignment="center",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )

            self.elements["tick5_text"] = self.ax.text(
                0,
                0,
                "0",
                horizontalalignment="right",
                verticalalignment="center",
                fontsize=self.fontsize,
                color=self.majorcolor,
                zorder=self.zorder,
            )
        else:
            raise Exception("Invalid orientation")

        # top / bottom / left / right bounds of box are same for vert/horiz.
        (self.elements["top"],) = self.ax.plot(
            [0, 0],
            [0, 0],
            color=self.majorcolor,
            zorder=self.zorder,
            linewidth=self.linewidth,
        )
        (self.elements["bottom"],) = self.ax.plot(
            [0, 0],
            [0, 0],
            color=self.majorcolor,
            zorder=self.zorder,
            linewidth=self.linewidth,
        )
        (self.elements["left"],) = self.ax.plot(
            [0, 0],
            [0, 0],
            color=self.majorcolor,
            zorder=self.zorder,
            linewidth=self.linewidth,
        )
        (self.elements["right"],) = self.ax.plot(
            [0, 0],
            [0, 0],
            color=self.majorcolor,
            zorder=self.zorder,
            linewidth=self.linewidth,
        )
        (self.elements["tick1"],) = self.ax.plot(
            0, 0, color=self.majorcolor, zorder=self.zorder, linewidth=self.linewidth
        )
        (self.elements["tick3"],) = self.ax.plot(
            0, 0, color=self.majorcolor, zorder=self.zorder, linewidth=self.linewidth
        )
        (self.elements["tick5"],) = self.ax.plot(
            0, 0, color=self.majorcolor, zorder=self.zorder, linewidth=self.linewidth
        )
        # Add box from left to 1/4 across
        (self.elements["box1"],) = self.ax.fill(
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            fc=self.majorcolor,
            ec=self.majorcolor,
            zorder=self.zorder,
        )

        # Add box from mid to 3/4 across
        (self.elements["box3"],) = self.ax.fill(
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            fc=self.majorcolor,
            ec=self.majorcolor,
            zorder=self.zorder,
        )

        if self.minorcolor is not None:
            # add box from 1/4 to 1/2 way across
            (self.elements["box2"],) = self.ax.fill(
                [0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0],
                fc=self.minorcolor,
                ec=self.majorcolor,
                zorder=self.zorder,
            )
            # Add box from mid to 3/4 across
            (self.elements["box4"],) = self.ax.fill(
                [0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0],
                fc=self.minorcolor,
                ec=self.majorcolor,
                zorder=self.zorder,
            )

    def _update_simple(self) -> None:
        xleft, xright, xcen, ybottom, ytop, ycen = self._calculate_bounds()
        if self.orientation == "horiz":
            self.elements["line"].set_data([xleft, xright], [ycen, ycen])
            self.elements["tick1"].set_data([xleft, xleft], [ybottom, ytop])
            self.elements["tick2"].set_data([xright, xright], [ybottom, ytop])
            length = np.abs((xright - xleft) / self.unit_factor)
            self.elements["label"].set_position([xcen, ytop])
        elif self.orientation == "vert":
            self.elements["line"].set_data([xcen, xcen], [ybottom, ytop])
            self.elements["tick1"].set_data([xleft, xright], [ybottom, ybottom])
            self.elements["tick2"].set_data([xleft, xright], [ytop, ytop])
            length = np.abs((ytop - ybottom) / self.unit_factor)
            self.elements["label"].set_position([xright, ycen])
        else:
            raise Exception("Invalid orientation")
        # Hacky way to provide up to 2 decimal points, where needed
        # For some of the ICECAP lines (e.g. TOT/JKB2d/X15a), this raises
        # ValueError: cannot convert float NaN to integer
        # For JKB2e lines, it doesn't.
        try:
            if np.abs(10 * np.round(10 * length) - int(np.round(100 * length))) > 0.5:
                label = f"{length:.2f} {self.unit_label}"
            elif np.abs(10 * np.round(length) - int(np.round(10 * length))) > 0.5:
                label = f"{length:.1f} {self.unit_label}"
            else:
                label = f"{int(np.round(length))} {self.unit_label}"
        except ValueError as ex:
            print(ex)
            print(f"xright = {xright}, xleft = {xleft}, factor = {self.unit_factor}")
            label = ""
        self.elements["label"].set_text(label)

    def _update_fancy(self) -> None:
        xleft, xright, xcen, ybottom, ytop, ycen = self._calculate_bounds()
        dx_bar = xright - xleft
        dy_bar = ytop - ybottom

        # TODO: These calculations are all duplicates of stuff in plot_fancy.
        # Maybe have plot_fancy be just "setup_fancy", then call update_fancy"?

        if self.orientation == "horiz":
            x2 = 0.5 * (xleft + xcen)
            x4 = 0.5 * (xcen + xright)
            bar_length = 1.0 * dx_bar / self.unit_factor

            xtick1 = [xleft, xleft]
            ytick1 = [ybottom - 0.5 * dy_bar, ybottom]
            xtick3 = [xcen, xcen]
            ytick3 = ytick1
            xtick5 = [xright, xright]
            ytick5 = ytick1

            xbox1 = [xleft, x2, x2, xleft, xleft]
            ybox1 = [ytop, ytop, ybottom, ybottom, ytop]
            xbox2 = [x2, xcen, xcen, x2, x2]
            ybox2 = [ytop, ytop, ybottom, ybottom, ytop]
            xbox3 = [xcen, x4, x4, xcen, xcen]
            ybox3 = [ytop, ytop, ybottom, ybottom, ytop]
            xbox4 = [x4, xright, xright, x4, x4]
            ybox4 = [ytop, ytop, ybottom, ybottom, ytop]

            xtitle = xcen
            ytitle = ytop + dy_bar

            textpos1 = [xleft, ybottom - dy_bar]
            textpos3 = [xcen, ybottom - dy_bar]
            textpos5 = [xright, ybottom - dy_bar]

        elif self.orientation == "vert":
            y2 = 0.5 * (ybottom + ycen)
            y4 = 0.5 * (ycen + ytop)
            bar_length = 1.0 * dy_bar / self.unit_factor

            xtick1 = [xleft - 0.5 * dx_bar, xleft]
            ytick1 = [ybottom, ybottom]
            xtick3 = xtick1
            ytick3 = [ycen, ycen]
            xtick5 = xtick1
            ytick5 = [ytop, ytop]

            xbox1 = [xleft, xleft, xright, xright, xleft]
            ybox1 = [ybottom, y2, y2, ybottom, ybottom]
            xbox2 = xbox1
            ybox2 = [y2, ycen, ycen, y2, y2]
            xbox3 = xbox1
            ybox3 = [ycen, y4, y4, ycen, ycen]
            xbox4 = xbox1
            ybox4 = [y4, ytop, ytop, y4, y4]

            xtitle = xright + dx_bar
            ytitle = ycen

            textpos1 = [xleft - dx_bar, ybottom]
            textpos3 = [xleft - dx_bar, ycen]
            textpos5 = [xleft - dx_bar, ytop]

        else:
            raise Exception("Invalid orientation")

        # Box outline is same for horizontal/vertical
        self.elements["top"].set_data([xleft, xright], [ytop, ytop])
        self.elements["bottom"].set_data([xleft, xright], [ybottom, ybottom])
        self.elements["left"].set_data([xleft, xleft], [ybottom, ytop])
        self.elements["right"].set_data([xright, xright], [ybottom, ytop])

        self.elements["tick1"].set_data(xtick1, ytick1)
        self.elements["tick3"].set_data(xtick3, ytick3)
        self.elements["tick5"].set_data(xtick5, ytick5)

        self.elements["box1"].set_xy(np.array([xbox1, ybox1]).T)
        self.elements["box3"].set_xy(np.array([xbox3, ybox3]).T)

        if self.minorcolor is not None:
            self.elements["box2"].set_xy(np.array([xbox2, ybox2]).T)
            self.elements["box4"].set_xy(np.array([xbox4, ybox4]).T)

        self.elements["title"].set_position([xtitle, ytitle])
        self.elements["tick1_text"].set_position(textpos1)
        self.elements["tick3_text"].set_position(textpos3)
        self.elements["tick5_text"].set_position(textpos5)

        # tick1 text will always be '0'
        self.elements["tick3_text"].set_text("%d" % int(0.5 * bar_length))
        self.elements["tick5_text"].set_text("%d" % int(bar_length))

    def _calculate_bounds(self) -> Tuple[float, float, float, float, float, float]:
        """
        Calculates the axis-unit bounds for the scalebar.
        Handles all conversions between unit_factor, and making scalebar a nice
        round length for printing.
        Returns xleft, xright, xcen, ybottom, ytop, ycen in data units.
        (Handles axes with xlim[1] < xlim[0])
        """
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        dx_ax = xlim[1] - xlim[0]
        dy_ax = ylim[1] - ylim[0]
        xsign = np.sign(dx_ax)
        ysign = np.sign(dy_ax)

        if self.coords == "abs":
            if self.orientation == "horiz":
                xleft = self.x0
                xright = self.x0 + xsign * self.length * self.unit_factor
                xcen = 0.5 * (xleft + xright)

                ycen = self.y0
                ybottom = ycen - 0.5 * dy_ax * self.width
                ytop = ycen + 0.5 * dy_ax * self.width

            elif self.orientation == "vert":
                ybottom = self.y0
                ytop = self.y0 + ysign * self.length * self.unit_factor
                ycen = 0.5 * (ybottom + ytop)

                xcen = self.x0
                xleft = xcen - 0.5 * dx_ax * self.width
                xright = xcen + 0.5 * dx_ax * self.width
            else:
                raise Exception("Invalid orientation")

        elif self.coords == "frac":
            if self.orientation == "horiz":
                xleft = xlim[0] + dx_ax * self.x0
                dx_bar_raw = dx_ax * self.length
                # This figures out if max sig fig is ones, tens, hundreds, etc ...
                max_pow_10 = np.floor(np.log(np.abs(dx_bar_raw)) / np.log(10.0))
                # We need an even length for the scalebar (so the fancy plot's
                # scalebar can have an integer middle tick), and want its dimension
                # to have at most two significant figures.
                round_units = 2 * 10 ** (max_pow_10 - 1)
                dx_bar_round = round_units * np.round(dx_bar_raw / round_units)
                # TODO: This was rounding into plot units, not data units ...
                xright = xleft + dx_bar_raw  # _round
                xcen = 0.5 * (xleft + xright)

                ycen = ylim[0] + dy_ax * self.y0
                ybottom = ycen - 0.5 * dy_ax * self.width
                ytop = ycen + 0.5 * dy_ax * self.width

            elif self.orientation == "vert":
                ybottom = ylim[0] + dy_ax * self.y0
                dy_bar_raw = dy_ax * self.length
                # This figures out if max sig fig is ones, tens, hundreds, etc ...
                max_pow_10 = np.floor(np.log(np.abs(dy_bar_raw)) / np.log(10.0))
                # We need an even length for the scalebar (so the fancy plot's
                # scalebar can have an integer middle tick), and want its dimension
                # to have at most two significant figures.
                round_units = 2 * 10 ** (max_pow_10 - 1)
                dy_bar_round = round_units * np.round(dy_bar_raw / round_units)
                ytop = ybottom + dy_bar_raw  # round
                ycen = 0.5 * (ybottom + ytop)

                xcen = xlim[0] + dx_ax * self.x0
                xleft = xcen - 0.5 * dx_ax * self.width
                xright = xcen + 0.5 * dx_ax * self.width

            else:
                raise Exception("Invalid orientation.")

        else:
            msg = "Invalid option %r for coords. (abs or frac)" % (self.coords)
            raise KeyError(msg)

        return xleft, xright, xcen, ybottom, ytop, ycen
