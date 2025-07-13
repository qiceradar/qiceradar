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

from typing import Tuple

import matplotlib
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT


def get_ax_shape(fig, ax) -> Tuple[int, int]:
    """
    returns axis width in pixels; used for being a bit clever about how much
    of the image we draw.
    """
    bbox = ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted())
    return fig.dpi * bbox.width, fig.dpi * bbox.height


class UnzoomableAxes(matplotlib.axes.Axes):
    name = "unzoomable"

    def can_pan(self) -> bool:
        return False

    def can_zoom(self) -> bool:
        return False


matplotlib.projections.register_projection(UnzoomableAxes)


class NavigationToolbar(NavigationToolbar2QT):
    """
    Toolbar that only displays the Pan, Zoom and Save Icons.
    (home/fwd/back don't work correctly here)
    """

    toolitems = [
        t for t in NavigationToolbar2QT.toolitems if t[0] in ["Pan", "Zoom", "Save"]
    ]

    def __init__(self, *args, **kwargs) -> None:
        super(NavigationToolbar, self).__init__(*args, **kwargs)
        # get rid of the one with the green checkbox
        self.layout().takeAt(3)


class SaveToolbar(NavigationToolbar2QT):
    """Toolbar that only displays the Save Icon."""

    toolitems = [t for t in NavigationToolbar2QT.toolitems if t[0] in ["Save"]]

    def __init__(self, *args, **kwargs) -> None:
        super(SaveToolbar, self).__init__(*args, **kwargs)
        # get rid of the one with the green checkbox
        self.layout().takeAt(1)
