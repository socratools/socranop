# soundcraft/installtool.py - post-install and pre-uninstall commands
#
# Implements post-install (install config files after having installed
# a wheel), and pre-uninstall (uninstall config files before
# uninstalling a wheel).
#
# Copyright (c) 2020 Jim Ramsay <i.am@jimramsay.com>
# Copyright (c) 2020,2021 Hans Ulrich Niedermann <hun@n-dimensional.de>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import abc
import argparse
import shutil
import time
from pathlib import Path
from string import Template


try:
    import gi  # noqa: F401 'gi' imported but unused
except ModuleNotFoundError:
    print(
        """
The PyGI library must be installed from your distribution; usually called
python-gi, python-gobject, python3-gobject, pygobject, or something similar.
"""
    )
    raise

# We only need the whole gobject and GLib thing here to catch specific exceptions
from gi.repository.GLib import Error as GLibError


import pydbus

import soundcraft

import soundcraft.constants as const

from soundcraft.dirs import get_dirs


def findDataFiles(subdir):
    """Walk through data files in the soundcraft module's ``data`` subdir``"""

    result = {}
    modulepaths = soundcraft.__path__
    for path in modulepaths:
        path = Path(path)
        datapath = path / "data" / subdir
        result[datapath] = []
        for f in datapath.glob("**/*"):
            if f.is_dir():
                continue  # ignore directories
            result[datapath].append(f.relative_to(datapath))
    return result


class AbstractInstallTool(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def post_install(self):
        pass  # AbstractInstallTool.post_install()

    @abc.abstractmethod
    def pre_uninstall(self):
        pass  # AbstractInstallTool.pre_uninstall()


class FileInstallTool(AbstractInstallTool):

    pass  # class FileInstallTool


class DBusInstallTool(FileInstallTool):
    def __init__(self):
        super(DBusInstallTool, self).__init__()
        service_dir = get_dirs().datadir / "dbus-1/services"
        self.service_dst = service_dir / f"{const.BUSNAME}.service"

    def post_install(self):
        templateData = {
            "dbus_service_bin": str(get_dirs().serviceExePath),
            "busname": const.BUSNAME,
        }

        sources = findDataFiles("dbus-1")
        for (srcpath, files) in sources.items():
            for f in files:
                src = srcpath / f
                if src.suffix == ".service":
                    print("Installing", self.service_dst)
                    self.service_dst.parent.mkdir(
                        mode=0o755, parents=True, exist_ok=True
                    )
                    srcTemplate = Template(src.read_text())
                    self.service_dst.write_text(srcTemplate.substitute(templateData))
                    self.service_dst.chmod(mode=0o644)

        print("Starting D-Bus service as a test...")

        bus = pydbus.SessionBus()
        dbus_service = bus.get(".DBus")
        print(f"Installtool version: {const.VERSION}")

        # Give the D-Bus a few seconds to notice the new service file
        timeout = 5
        while True:
            try:
                dbus_service.StartServiceByName(const.BUSNAME, 0)
                break  # service has been started, no need to try again
            except GLibError:
                # If the bus has not recognized the service config file
                # yet, the service is not bus activatable yet and thus the
                # GLibError will happen.
                if timeout == 0:
                    raise
                timeout = timeout - 1

                time.sleep(1)
                continue  # starting service has failed, but try again

        our_service = bus.get(const.BUSNAME)
        service_version = our_service.version
        print(f"Service     version: {service_version}")

        print("Shutting down session D-Bus service...")
        # As the service should either be running at this time or
        # at the very least be bus activatable, we do not catch
        # any exceptions while shutting it down because we want to
        # see any exceptions if they happen.
        our_service.Shutdown()
        print("Session D-Bus service has been shut down")

        print("D-Bus installation is complete")
        print(f"Run {const.BASE_EXE_GUI} or {const.BASE_EXE_CLI} as a regular user")

    def pre_uninstall(self):
        bus = pydbus.SessionBus()
        dbus_service = bus.get(".DBus")
        if not dbus_service.NameHasOwner(const.BUSNAME):
            print("D-Bus service not running")
        else:
            service = bus.get(const.BUSNAME)
            service_version = service.version
            print(f"Shutting down D-Bus service version {service_version}")
            service.Shutdown()
            print("Session D-Bus service stopped")

        print(f"Removing {self.service_dst}")
        try:
            self.service_dst.unlink()
        except FileNotFoundError:
            pass  # No service file to remove

        print("D-Bus service is unregistered")


class XDGDesktopInstallTool(FileInstallTool):

    # FIXME05: Find out whether `xdg-desktop-menu` and `xdg-desktop-icon`
    #          must be run after all. Fedora Packaging docs suggest so.

    def post_install(self):
        sources = findDataFiles("xdg")
        dirs = get_dirs()
        for (srcpath, files) in sources.items():
            for f in files:
                src = srcpath / f
                if src.suffix == ".desktop":
                    application_dir = dirs.datadir / "applications"
                    dst = application_dir / f"{const.APPLICATION_ID}.desktop"
                    templateData = {
                        "gui_bin": dirs.guiExePath,
                        "APPLICATION_ID": const.APPLICATION_ID,
                    }
                    srcTemplate = Template(src.read_text())
                    print("Installing", dst)
                    dst.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    dst.write_text(srcTemplate.substitute(templateData))
                    dst.chmod(mode=0o644)
                elif src.suffix == ".png":
                    size_suffix = src.suffixes[-2]
                    assert size_suffix.startswith(".")
                    size = int(size_suffix[1:], 10)
                    dst = self.icondir(size) / f"{const.APPLICATION_ID}.png"
                    print("Installing", dst)
                    dst.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    shutil.copy(src, dst)
                    dst.chmod(mode=0o644)
                elif src.suffix == ".svg":
                    dst = self.icondir() / f"{const.APPLICATION_ID}.svg"
                    print("Installing", dst)
                    dst.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    shutil.copy(src, dst)
                    dst.chmod(mode=0o644)
        print("Installed all XDG application launcher files")

    def pre_uninstall(self):
        sources = findDataFiles("xdg")
        dirs = get_dirs()
        for (srcpath, files) in sources.items():
            for f in files:
                src = srcpath / f
                if src.suffix == ".desktop":
                    application_dir = dirs.datadir / "applications"
                    dst = application_dir / f"{const.APPLICATION_ID}.desktop"
                    print(f"Uninstalling {dst}")
                    try:
                        dst.unlink()
                    except FileNotFoundError:
                        pass  # No dst file to remove
                elif src.suffix == ".png":
                    size_suffix = src.suffixes[-2]
                    assert size_suffix.startswith(".")
                    size = int(size_suffix[1:], 10)
                    dst = self.icondir(size) / f"{const.APPLICATION_ID}.png"
                    print(f"Uninstalling {dst}")
                    try:
                        dst.unlink()
                    except FileNotFoundError:
                        pass  # No dst file to remove
                elif src.suffix == ".svg":
                    dst = self.icondir() / f"{const.APPLICATION_ID}.svg"
                    print(f"Uninstalling {dst}")
                    try:
                        dst.unlink()
                    except FileNotFoundError:
                        pass  # No dst file to remove
        print("Removed all XDG application launcher files")

    def icondir(self, size=None):
        dirs = get_dirs()
        if size is None:
            return dirs.datadir / "icons/hicolor/scalable/apps"
        else:
            return dirs.datadir / f"icons/hicolor/{size}x{size}/apps"


class InstallToolEverything(AbstractInstallTool):
    """Groups all subsystem installtools"""

    def __init__(self):
        super(InstallToolEverything, self).__init__()
        self.everything = []

    def add(self, thing):
        self.everything.append(thing)

    def post_install(self):
        for thing in self.everything:
            thing.post_install()

    def pre_uninstall(self):
        for thing in reversed(self.everything):
            thing.pre_uninstall()


def main():
    parser = argparse.ArgumentParser(
        description=f"hook {const.PACKAGE} into the system post-install (or do the reverse)"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s ({const.PACKAGE}) {const.VERSION}",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--post-install",
        help=f"Install and set up {const.PACKAGE} and exit",
        action="store_true",
    )
    group.add_argument(
        "--pre-uninstall",
        help="Undo any installation and setup performed by --post-install and exit",
        action="store_true",
    )

    args = parser.parse_args()

    # Initialize the dirs object
    dirs = get_dirs()
    print("Using dirs", dirs)

    everything = InstallToolEverything()
    everything.add(DBusInstallTool())
    everything.add(XDGDesktopInstallTool())

    if args.post_install:
        everything.post_install()
    elif args.pre_uninstall:
        everything.pre_uninstall()
