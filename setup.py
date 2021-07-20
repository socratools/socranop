# Call setuptools.setup
#
# As we are lazy in defining possibly redundant information, we have
# put a lot of information into the socranop.constants module and
# import that module both from this setup.py and whzen the actual
# software package is running.
#
# If we were to use importlib.metadata, we could move from setup.py to
# setup.cfg and get to information like the package version from the
# software package itself. Unfortunately, importlib.metadata is only
# available in Python >= 3.8, but we want to support Python 3.6.

import socranop.constants as const

from pathlib import Path
from setuptools import find_packages, setup

# Make sure we have imported the correct `socranop.constants`. The
# `PYTHONPATH` (aka `sys.path`) could be set up weirdly, and we do not
# want to fall victim to such sabotage attempts, deliberate or
# accidental.
topdir_from_const = Path(const.__file__).parent.parent
topdir_from_setup = Path(__file__).parent
if not topdir_from_setup.samefile(topdir_from_const):
    raise Exception(
        f"inconsistent locations of socranop.constants and setup.py: {topdir_from_const} vs {topdir_from_setup}"
    )

readme_md_path = topdir_from_setup / "README.md"
readme_text = readme_md_path.read_text("utf-8")

# Filter out screenshot images which do work on github, but not on pypi
long_description = "".join(
    [f"{line}\n" for line in readme_text.splitlines() if not line.startswith("![")]
)

setup(
    name=const.PACKAGE,
    version=const.VERSION,
    description="Soundcraft Notepad control utilities",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Jim Ramsay",
    author_email="i.am@jimramsay.com",
    url="https://github.com/socratools/socranop",
    license="MIT",
    packages=find_packages(),
    # https://pypi.org/classifiers/
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Multimedia :: Sound/Audio :: Mixers",
    ],
    python_requires=">=3.6",
    install_requires=["pyusb", "pydbus"],
    dependency_links=[],
    entry_points={
        "console_scripts": [
            f"{const.BASE_EXE_CLI}=socranop.cli:main",
            f"{const.BASE_EXE_SERVICE}=socranop.dbus:service_main",
            f"{const.BASE_EXE_INSTALLTOOL}=socranop.installtool:main",
        ],
        "gui_scripts": [f"{const.BASE_EXE_GUI}=socranop.gui:main"],
    },
    include_package_data=True,
)
