# radar_viewer


## mypy

Eventually, this should be automated in CI + install, but for now, run mypy manually:

pip install PyQt5-stubs
python3 -m pip install qgis-stubs
pip install types-PyYAML
python3 -m pip install mypy

mypy radar*.py