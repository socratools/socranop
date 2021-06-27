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


"""\
Determine directories adequate for the detected installation type

Supported installation types are:

  * global installation to ``/usr/``
  * global installation to ``/usr/local/``
  * local installation to ``$HOME/.local/``
  * local installation to ``$HOME/.local/share/virtualenv/WHATEVER/``
    (by installing the config files to ``$HOME/.local/``

The ``chroot=`` parameter to ``init_dirs()`` is used when building
binary packages for distributions. Apart from that one use, users of
this module only need to call ``get_dirs()`` to get the object
representing the current installation.

When accessed only through ``get_dirs()`` and optionally
``init_dirs(...)``, this module defines a single object, as the
installation type is a global constant which needs to be determined
only once, and cannot change during one program invocation.
"""


import abc
import sys

from os import getenv
from pathlib import Path

import soundcraft.constants as const


class NotDetected(Exception):
    pass  # class NotDetected


class UnsupportedInstall(Exception):
    pass  # class UnsupportedInstall


class AbstractDirs(metaclass=abc.ABCMeta):
    def __init__(self, chroot=None):
        super(AbstractDirs, self).__init__()

        if chroot:
            self._chroot = Path(chroot)
        else:
            self._chroot = None

        self._prefix = None
        self._statedir = None

        print("AbstractDirs.__init__", self, f"chroot={chroot!r}")

        self.__detect()

    def __str__(self):
        props = ["chroot", "prefix", "datadir", "statedir"]

        def c(obj):
            if isinstance(obj, Path):
                return str(obj)
            else:
                return obj

        ps = ", ".join([("%s=%r" % (p, c(getattr(self, p)))) for p in props])
        return f"{self.__class__.__name__}({ps})"

    @property
    def chroot(self):
        return self._chroot

    def __remove_chroot(self, path):
        if self.chroot is None:
            return path
        else:
            rel_path = path.relative_to(self.chroot)
            return Path(f"/{rel_path}")

    @property
    def exePath(self):
        """The path the currently running executable"""
        exename = Path(sys.argv[0]).resolve()
        if exename.suffix == ".py":
            raise ValueError("Running out of a module-based execution is not supported")
        return exename

    @property
    def guiExePath(self):
        """Full path to the gui script executable"""
        return self.__remove_chroot(self.exePath.parent / const.BASE_EXE_GUI)

    @property
    def serviceExePath(self):
        """Full path to the service script executable"""
        return self.__remove_chroot(self.exePath.parent / const.BASE_EXE_SERVICE)

    def __detect(self):
        """Detect whether the current installation matches this class.

        Call this from __init__().
        """

        if self.chroot is None:
            chr_prefix = self.PREFIX
        else:
            root_rel_prefix = self.PREFIX.relative_to("/")
            chr_prefix = self.chroot / root_rel_prefix

        for sx_dir in ["bin", "sbin", "libexec"]:
            for sx in [
                const.BASE_EXE_CLI,
                const.BASE_EXE_GUI,
                const.BASE_EXE_SERVICE,
                const.BASE_EXE_INSTALLTOOL,
            ]:
                sx_path = chr_prefix / sx_dir / sx
                # print("sx_path", sx_path)
                if sx_path == self.exePath:
                    return
                try:
                    self.exePath.relative_to(chr_prefix)  # ignore result

                    # If this is, say,
                    # ``/home/user/.local/share/virtualenvs/soundcraft-utils-ABCDEFG/bin/soundcraft_installtool``,
                    # then the D-Bus and XDG config can either go into
                    # ``/home/user/.local/share/virtualenvs/soundcraft-utils-ABCDEFG/share/``
                    # and be ignored, or go into
                    # ``/home/user/.local/share/`` and work. We choose
                    # the latter.
                    return
                except ValueError:
                    pass  # self.exePath is not a subdir of chr_prefix

        raise NotDetected(f"Exe path is not supported: {self.exePath!r}")

    @property
    def prefix(self):
        """The prefix corresponding to the installation type of the currently running executable"""
        return self.PREFIX

    @property
    def datadir(self):
        """The datadir corresponding to the installation type of the currently running executable"""
        return self.prefix / "share"

    @property
    def statedir(self):
        """The statedir where the device state files are stored

        The state directory for a user session service must be somewhere
        in the user's ``$HOME``, and a config file is a good place.
        """
        if self._statedir is None:
            config_dir = Path("~/.config").expanduser()

            xdg_config_home = getenv("XDG_CONFIG_HOME")
            if xdg_config_home:  # neither None nor empty string
                xdg_config_home_path = Path(xdg_config_home)
                config_dir = xdg_config_home_path

            self._statedir = config_dir / const.PACKAGE / "state"

        return self._statedir


class GlobalDirs(AbstractDirs):
    pass  # class GlobalDirs


class UsrDirs(GlobalDirs):
    """Global install to /usr"""

    PREFIX = Path("/usr")


class UsrLocalDirs(GlobalDirs):
    """Global install to /usr/local"""

    PREFIX = Path("/usr/local")


class HomeDirs(AbstractDirs):
    """User local install to $HOME/.local"""

    PREFIX = Path("~/.local").expanduser()


# The one instance of an AbstractDirs descendant class
__dir_instance = None


def init_dirs(chroot=None):
    global __dir_instance

    assert __dir_instance is None

    for cls in [UsrLocalDirs, UsrDirs, HomeDirs]:
        try:
            __dir_instance = cls(chroot)
            print("Using dirs:", __dir_instance)
            return __dir_instance
        except NotDetected:
            pass  # This installation is not for the current cls

    raise UnsupportedInstall(
        "exename=%r, chroot=%r" % (str(Path(sys.argv[0]).resolve()), chroot)
    )


def get_dirs():
    global __dir_instance

    if __dir_instance is None:
        init_dirs()

    return __dir_instance
