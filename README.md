# radar_viewer

These READMEs are written for people who want to edit the plugin.
See (TODO!!) for user-facing documentation.


## Development setup

Install the "Plugin Reloader" plugin; it allows you to reload a plugin after changing the code without having to restart QGIS.

### code management

Plugins are installed to a folder managed by QGIS; it's not safe to do development there, since uninstalling a plugin deletes its directory.

Instead, you either need a deploy script that copies your working files
to the QGIS folder, or create a symlink from the directory that
QGIS looks for to where you're actually doing development.

On my computer (MacOS), QGIS looks for plugins in:
~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/


## Code structure



## mypy

Eventually, this should be automated in CI + install, but for now, run mypy manually:

pip install PyQt5-stubs
python3 -m pip install qgis-stubs
pip install types-PyYAML
python3 -m pip install mypy

mypy radar*.py