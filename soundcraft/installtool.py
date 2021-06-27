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

from soundcraft.dirs import get_dirs, init_dirs


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


class AbstractFile(metaclass=abc.ABCMeta):
    """Common behaviour for different types of files defined as Subclasses"""

    def __init__(self, dst):
        super(AbstractFile, self).__init__()
        self.__dst = Path(dst)

    @property
    def dst(self):
        return self.__dst

    @property
    def chroot_dst(self):
        chroot = get_dirs().chroot
        if chroot:
            relpath = self.dst.relative_to("/")
            return chroot / relpath
        else:
            return self.dst

    @abc.abstractmethod
    def install(self):
        pass  # AbstractFile.install()

    def uninstall(self):
        # Like many other install/uninstall tools, we just remove the
        # file and leave the directory tree around.
        self.uninstall_msg(self.dst)
        try:
            self.chroot_dst.unlink()
        except FileNotFoundError:
            pass  # No file to remove

    def install_msg(self, dst):
        print("  [inst]", dst)

    def uninstall_msg(self, dst):
        print("  [rm]", dst)


class CopyFile(AbstractFile):
    """This file just needs to be copied from a source file to the destination"""

    def __init__(self, dst, src):
        super(CopyFile, self).__init__(dst)
        self.__src = Path(src)

    @property
    def src(self):
        return self.__src

    def install(self):
        self.install_msg(self.dst)
        self.chroot_dst.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        shutil.copy(self.src, self.chroot_dst)
        self.chroot_dst.chmod(mode=0o644)


class StringToFile(AbstractFile):
    """This destination file is written from a string, no source file required"""

    def __init__(self, dst, content):
        super(StringToFile, self).__init__(dst)

        self.content = content

    def install(self):
        self.install_msg(self.dst)
        self.chroot_dst.parent.mkdir(mode=0o0755, parents=True, exist_ok=True)
        self.chroot_dst.write_text(self.content)
        self.chroot_dst.chmod(mode=0o0644)


class TemplateFile(CopyFile):
    """This destination file is a source file after string template processing"""

    def __init__(self, dst, src, template_data=None):
        super(TemplateFile, self).__init__(dst, src)

        if template_data is None:
            self.template_data = {}
        else:
            self.template_data = template_data

    def install(self):
        self.install_msg(self.dst)
        src_template = Template(self.src.read_text())
        self.chroot_dst.parent.mkdir(mode=0o0755, parents=True, exist_ok=True)
        self.chroot_dst.write_text(src_template.substitute(self.template_data))
        self.chroot_dst.chmod(mode=0o0644)


class AbstractInstallTool(metaclass=abc.ABCMeta):
    """Things common to subsystem installtools"""

    @abc.abstractmethod
    def post_install(self):
        pass  # AbstractInstallTool.post_install()

    @abc.abstractmethod
    def pre_uninstall(self):
        pass  # AbstractInstallTool.pre_uninstall()


class FileInstallTool(AbstractInstallTool):
    """A subsystem which needs to install/uninstall a number of files"""

    def __init__(self):
        super(FileInstallTool, self).__init__()
        self.files = []

    def add_file(self, file):
        self.files.append(file)

    def post_install(self):
        for file in self.files:
            file.install()

    def pre_uninstall(self):
        for file in reversed(self.files):
            file.uninstall()


class DataFileInstallTool(FileInstallTool):
    """Some installtool which iterates through files in data/"""

    def walk_through_data_files(self, subdir):
        sources = findDataFiles(subdir)
        for (srcpath, files) in sources.items():
            for f in sorted(files):
                src = srcpath / f
                ssrc = str(src)
                if ssrc[-1] == "~":
                    continue  # ignore backup files ending with a tilde
                self.add_src(src)

    @abc.abstractmethod
    def add_src(self, src):
        """Examine src file and decide what to do about it

        Examine the given source file ``src`` and then decide whether
        to

          * ``self.add_file()`` an instance of ``AbstractFile``
          * ``raise UnhandledDataFile(src)``
        """
        pass  # DataFileInstallTool.add_src()


class UnhandledDataFile(Exception):
    """Unhandled data file encountered while walking through data tree"""

    pass  # class UnhandledDataFile


class DBusInstallTool(DataFileInstallTool):
    """Subsystem dealing with the D-Bus configuration files"""

    def __init__(self, no_launch):
        super(DBusInstallTool, self).__init__()
        self.no_launch = no_launch

        self.walk_through_data_files("dbus-1")

    def add_src(self, src):
        if src.suffix == ".service":
            dirs = get_dirs()
            templateData = {
                "dbus_service_bin": str(dirs.serviceExePath),
                "busname": const.BUSNAME,
            }

            service_dir = dirs.datadir / "dbus-1/services"
            service_dst = service_dir / f"{const.BUSNAME}.service"

            service_file = TemplateFile(service_dst, src, template_data=templateData)
            self.add_file(service_file)
        else:
            raise UnhandledDataFile(src)

    def post_install(self):
        super(DBusInstallTool, self).post_install()

        if not self.no_launch:
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
        if not self.no_launch:
            bus = pydbus.SessionBus()
            dbus_service = bus.get(".DBus")
            if not dbus_service.NameHasOwner(const.BUSNAME):
                print("D-Bus service not running")
            else:
                print(f"Installtool version: {const.VERSION}")
                service = bus.get(const.BUSNAME)
                service_version = service.version
                print(f"Shutting down D-Bus service version {service_version}")
                service.Shutdown()
                print("Session D-Bus service stopped")

        super(DBusInstallTool, self).pre_uninstall()
        print("D-Bus service is unregistered")


class XDGDesktopInstallTool(DataFileInstallTool):
    """Subsystem dealing with the XDG desktop and icon files"""

    # FIXME05: Find out whether `xdg-desktop-menu` and `xdg-desktop-icon`
    #          must be run after all. Fedora Packaging docs suggest so.

    def __init__(self):
        super(XDGDesktopInstallTool, self).__init__()
        self.walk_through_data_files("xdg")

    def add_src(self, src):
        if src.suffix == ".desktop":
            dirs = get_dirs()
            applications_dir = dirs.datadir / "applications"
            dst = applications_dir / f"{const.APPLICATION_ID}.desktop"
            templateData = {
                "gui_bin": dirs.guiExePath,
                "APPLICATION_ID": const.APPLICATION_ID,
            }
            self.add_file(TemplateFile(dst, src, templateData))
        elif src.suffix == ".png":
            size_suffix = src.suffixes[-2]
            assert size_suffix.startswith(".")
            size = int(size_suffix[1:], 10)
            dst = self.icondir(size) / f"{const.APPLICATION_ID}.png"
            self.add_file(CopyFile(dst, src))
        elif src.suffix == ".svg":
            dst = self.icondir() / f"{const.APPLICATION_ID}.svg"
            self.add_file(CopyFile(dst, src))
        else:
            raise UnhandledDataFile(src)

    def post_install(self):
        super(XDGDesktopInstallTool, self).post_install()
        print("Installed all XDG application launcher files")

    def pre_uninstall(self):
        super(XDGDesktopInstallTool, self).pre_uninstall()
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

    parser.add_argument(
        "--no-launch",
        help="when installing, do not test launching the service",
        action="store_true",
    )

    parser.add_argument(
        "--chroot",
        metavar="CHROOT",
        help="chroot dir to (un)install from/into (implies --no-launch)",
        default=None,
    )

    args = parser.parse_args()
    if args.chroot:
        # If chroot is given, the service file is installed inside the chroot
        # and starting/stopping the service does not make sense.
        args.no_launch = True

    if args.chroot:
        print("Using chroot", args.chroot)

    # Initialize the dirs object with the chroot given so that later
    # calls to get_dirs() will yield an object which uses the same
    # chroot value.
    dirs = init_dirs(chroot=args.chroot)
    print("Using dirs", dirs)

    everything = InstallToolEverything()
    everything.add(DBusInstallTool(no_launch=args.no_launch))
    everything.add(XDGDesktopInstallTool())

    if args.post_install:
        everything.post_install()
    elif args.pre_uninstall:
        everything.pre_uninstall()
