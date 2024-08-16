
## Download Index

The index of Antarctic radar depth sounding data is on Zenodo: https://zenodo.org/records/12123014

Download `qiceradar_antarctic_index.gpkg` and `qiceradar_antarctic_index.qlr`:

* Save them into the same directory
* Do not rename the files

Open QGIS, open the project that you want to add the index to, then drag `qiceradar_antarctic_index.qlr` into the map pane.

![](.figures/qgis_index.png)
*Screeshot of QGIS, after importing the index layer. Groundtracks of publicly-available radargrams are in dark grey, and groundtracks for unavailable radargrams are in red.*

This index has been compiled from the BedMAP3 data[1] (red lines) and coordinates extracted from the published radargrams (grey lines). Radar lines are grouped into surveys/campaigns and then into institutions, following the Bedmap3 classifications.

The QIceRadar plugins depend on the structure of this data:
* Import all features; selecting individual features to import will not work with the plugins. (If necessary, you can delete layers/institution groups after importing.)
* Do not rename the top-level group. If you do so, the plugin won't be able to find the data. It should be "ANTARCTIC QIceRadar Index"


## Install Plugin

### Option 1: from QGIS's plugins repository

NOT YET SUPPORTED; waiting to be included in their repo

In QGIS, Plugins -> "Manage and Install Plugins..."

Select "all" in the left pane, then search for qiceradar

select qiceradar, then click "Install Plugin"

### Option 2: zipped source code

Go to https://github.com/qiceradar/qiceradar_plugin
* Click "Code" -> "Download Zip"

In QGIS:
* Plugins -> "Manage and Install Plugins..."
* Click "Install from zip"
* Select the file downloaded earlier, and click "Install Plugin"


### Python dependencies
The QIceRadar radar_viewer plugin has dependencies on several python packages that may or may not have been packaged with your install of QGIS.

If you get an error like `ModuleNotFoundError: No module named 'netCDF4'`, you'll need to install that module.
If you installed the plugin without errors, skip this section!


QGIS uses its own install of Python, so when installing dependencies
be sure to install into that version, rather than the default system install.

On Windows, follow this guide: https://landscapearchaeology.org/2018/installing-python-packages-in-qgis-3-for-windows/


On MacOS,
Figure out where QGIS's python is installed:
Plugins -> Python Console
~~~
import sys
print(sys.executable)
~~~
On my machine, this prints \
"/Applications/QGIS-LTR.app/Contents/MacOS/QGIS"

So, I'll use that version of pip: \
`/Applications/QGIS-LTR.app/Contents/MacOS/bin/pip3 install [module name]`


#### References
[1] Frémand, Alice C., et al. "Antarctic Bedmap data: FAIR sharing of 60 years of ice bed, surface and thickness data." Earth System Science Data Discussions 2022 (2022): 1-25.


