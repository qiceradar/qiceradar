import numpy as np
import os

import matplotlib
import matplotlib.pyplot as plt

import scalebar

fig = plt.figure()
ax = fig.add_axes([0,0,1,1])

circle = matplotlib.patches.Circle([0, 0], 500000, color='k', fill=False)
ax.add_artist(circle)
ax.set_xlim([-2e6, 2e6])
ax.set_ylim([-2e6, 2e6])
ax.axis('equal')

# lower-left corner gets simple, relatively-positioned horizontal scalebar
s1 = scalebar.Scalebar(ax, 0.05, 0.05, 0.15, 0.02,
                       barstyle='simple', coords='frac', orientation='horiz',
                       unit_label='km', unit_factor=1000) #label and scale factor from map axes

# lower left side gets simple, relatively-positioned VERTICAL scalebar
s5 = scalebar.Scalebar(ax, 0.05, 0.25, 0.15, 0.02,
                       barstyle='simple', coords='frac', orientation='vert',
                       unit_label='km', unit_factor=1000) #label and scale factor from map axes

# upper-left corner gets fancy, relatively-positioned horizontal scalebar
s2 = scalebar.Scalebar(ax, 0.05, 0.85, 0.15, 0.02,
                       barstyle='fancy', coords='frac', orientation='horiz',
                       unit_label='km', unit_factor=1000) #label and scale factor from map axes

# upper left side  gets fancy, relatively-positioned vertical scalebar
s6 = scalebar.Scalebar(ax, 0.1, 0.5, 0.2, 0.015,
                       barstyle='fancy', coords='frac', orientation='vert',
                       unit_label='km', unit_factor=1000) #label and scale factor from map axes

# lower-right corner gets simple, absolutely-positioned horizontal scalebar
s3 = scalebar.Scalebar(ax, 0.75e6, -1e6, 1000, 0.02,
                       barstyle='simple', coords='abs', orientation='horiz',
                       unit_label='km', unit_factor=1000) #label and scale factor from map axes

# lower-right side gets simple, absolutely-positioned vertical scalebar
s7 = scalebar.Scalebar(ax, 1.0e6, -0.75e6, 500, 0.02,
                       barstyle='simple', coords='abs', orientation='vert',
                       unit_label='km', unit_factor=1000) #label and scale factor from map axes

# upper-right corner gets fancy, absolutely-positioned horizontal scalebar
s4 = scalebar.Scalebar(ax, 0.75e6, 1e6, 1000, 0.02,
                       barstyle='fancy', coords='abs', orientation='horiz',
                       unit_label='km', unit_factor=1000)

# upper right side gets fancy, absolutely-positioned vertical
s8 = scalebar.Scalebar(ax, 1e6, 0, 500, 0.02,
                       barstyle='fancy', coords='abs', orientation='vert',
                       unit_label='km', unit_factor=1000)

ax.set_xlim([-2e6, 2e6])
ax.set_ylim([-2e6, 2e6])

plt.show()
