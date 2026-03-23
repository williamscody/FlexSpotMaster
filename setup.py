from distutils.core import setup
import py2exe


setup(
    windows=[{"script": "FlexSpotMaster.py"}],
    options={
        "py2exe": {
            "bundle_files": 1,
            "compressed": True,
            "optimize": 2,
            "includes": ["tkinter"],
            "packages": ["PIL"],
        }
    },
    zipfile=None,
)
