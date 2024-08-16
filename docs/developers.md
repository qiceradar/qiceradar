
# Developer Documentation


## Development setup

Install the "Plugin Reloader" plugin; it allows you to reload a plugin after changing the code without having to restart QGIS.

* in QGIS, Plugins -> "Manage and Install Plugins..."
* Select "all" in the left pane, then search for reloader
* Select "Plugin Reloader", then click "Install Plugin"

### code management

Plugins are installed to a folder managed by QGIS; it's not safe to do development there, since uninstalling a plugin deletes its directory.

Instead, you either need a deploy script that copies your working files
to the QGIS folder, or create a symlink from the directory that
QGIS looks for to where you're actually doing development.

In order to figure out where QGIS will look for plugins:

* in QGIS, Settings -> "User Profiles" -> "Open Active Profile Folder"
* From that directory, open python -> plugins. This is where plugins will be installed, and where you should clone to.

~~~
cd [Active Profile Folder]/python/plugins
git clone https://github.com/qiceradar/qiceradar_plugin
~~~

Then, make sure it is installed in QGIS:
* Plugins -> "Manage and Install Plugins..."
* search for "qiceradar"
* If not already checked, select it. You may need to click "Install Plugin"


## Code structure



## mypy

Eventually, this should be automated in CI + install, but for now, run mypy manually:

pip install PyQt5-stubs
python3 -m pip install qgis-stubs
pip install types-PyYAML
python3 -m pip install mypy

mypy radar*.py