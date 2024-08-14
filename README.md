# QIceRadar radar_viewer QGIS plugin

TODO: quick blurb about QIceRadar, include screencap!

TODO: "See a demo here!"

## Download index of radar depth sounding data

The radargram index is on Zenodo: https://zenodo.org/records/12123014

Download `qiceradar_antarctic_index.gpkg` and `qiceradar_antarctic_index.qlr`

* Save them into the same directory
* Do not rename the files

Open QGIS, open the project that you want to add the index to, then drag `qiceradar_antarctic_index.qlr` into the map pane.

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

First, install the "Plugin Reloader" plugin; it will come in handy.

* in QGIS, Plugins -> "Manage and Install Plugins..."
* Select "all" in the left pane, then search for reloader
* Select "Plugin Reloader", then click "Install Plugin"

Next, figure out where QGIS will look for plugins:

* in QGIS, Settings -> "User Profiles" -> "Open Active Profile Folder"
* From that directory, open python -> plugins. This is where plugins will be installed.

Finally, go to https://github.com/qiceradar/qiceradar_plugin
* Click "Code" -> "Download Zip"
* Extract the zipped folder into the directory found above. You should wind up with: [Active Profile Folder]/python/plugins/qiceradar_plugin/[all the plugin's code]

(If you're comfortable with git, you can also `git clone https://github.com/qiceradar/qiceradar_plugin` into the plugins folder.)

### Python dependencies
If you get an error like "ModuleNotFoundError: No module named 'netCDF4'", you'll need to install that module.
If you install the plugin without errors, skip this section!

The QIceRadar radar_viewer plugin has dependencies on several python
packages that may or may not have been packaged with your install of QGIS.

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


## Usage Tutorial

TODO: add screenshots/walkthrough, based on what I plan to do for the tutorial?



# Developer Documentation


## Development setup

Install the "Plugin Reloader" plugin; it allows you to reload a plugin after changing the code without having to restart QGIS.

### code management

Plugins are installed to a folder managed by QGIS; it's not safe to do development there, since uninstalling a plugin deletes its directory.

Instead, you either need a deploy script that copies your working files
to the QGIS folder, or create a symlink from the directory that
QGIS looks for to where you're actually doing development.


## Code structure



## mypy

Eventually, this should be automated in CI + install, but for now, run mypy manually:

pip install PyQt5-stubs
python3 -m pip install qgis-stubs
pip install types-PyYAML
python3 -m pip install mypy

mypy radar*.py