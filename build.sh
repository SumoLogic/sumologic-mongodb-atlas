python setup.py bdist_wheel
pip uninstall -y sumologic_mongodb_atlas
pip install dist/sumologic_mongodb_atlas*.whl
