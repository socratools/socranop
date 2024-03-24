# socranop/dirs.py - Determine installation directories
#
# Copyright (c) 2020,2021 Jim Ramsay <i.am@jimramsay.com>
# Copyright (c) 2020,2021,2023 Hans Ulrich Niedermann <hun@n-dimensional.de>
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

from functools import cache, cached_property
from logging import debug, info
from os import getenv
from pathlib import Path

import socranop.constants as const


class NotDetected(Exception):
    pass  # class NotDetected


class UnsupportedInstall(Exception):
    pass  # class UnsupportedInstall


@cache
def exePath():
    """The path the currently running executable"""
    exename = Path(sys.argv[0]).resolve()
    if exename.suffix == ".py":
        raise ValueError("Running out of a module-based execution is not supported")
    return exename


class AbstractDirs(metaclass=abc.ABCMeta):
    def __init__(self, chroot=None):
        super(AbstractDirs, self).__init__()

        if chroot:
            self._chroot = Path(chroot)
        else:
            self._chroot = None

        self._prefix = None

        debug("AbstractDirs.__init__(%s, %s)", self, f"chroot={chroot!r}")

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

    def __repr__(self):
        return self.__str__()

    @property
    def chroot(self):
        return self._chroot

    def remove_chroot(self, path):
        if self.chroot is None:
            return path
        else:
            rel_path = path.relative_to(self.chroot)
            return Path("/") / rel_path

    @property
    def guiExePath(self):
        """Full path to the GUI script executable"""
        return self.remove_chroot(exePath().parent / const.BASE_EXE_GUI)

    @property
    def serviceExePath(self):
        """Full path to the service script executable"""
        return self.remove_chroot(exePath().parent / const.BASE_EXE_SERVICE)

    def __detect(self):
        """Detect whether the current installation matches this class.

        Call this from __init__().
        """

        if self.chroot is None:
            chroot_plus_prefix = self.PREFIX
        else:
            root_rel_prefix = self.PREFIX.relative_to("/")
            chroot_plus_prefix = self.chroot / root_rel_prefix

        debug("detect: chroot_plus_prefix is %s", chroot_plus_prefix)

        for sx_dir in ["bin", "sbin", "libexec"]:
            for sx in [
                const.BASE_EXE_CLI,
                const.BASE_EXE_GUI,
                const.BASE_EXE_SERVICE,
                const.BASE_EXE_INSTALLTOOL,
            ]:
                sx_path = chroot_plus_prefix / sx_dir / sx
                if sx_path == exePath():
                    debug("found exe path inside chroot_plus_prefix %s", sx_path)
                    return
                try:
                    exePath().relative_to(chroot_plus_prefix)  # ignore result

                    # If this is, say,
                    # ``/home/user/.local/share/virtualenvs/socranop-ABCDEFG/bin/socranop-installtool``,
                    # then the D-Bus and XDG config can either go into
                    # ``/home/user/.local/share/virtualenvs/socranop-ABCDEFG/share/``
                    # and be ignored, or go into
                    # ``/home/user/.local/share/`` and work. We choose
                    # the latter.
                    return
                except ValueError:
                    pass  # exePath() is not in a subdir of chroot_plus_prefix

        raise NotDetected(f"Exe path is not supported: {exePath()!r}")

    @cached_property
    def prefix(self):
        """The prefix corresponding to the installation type of the currently running executable"""
        prefix = self.PREFIX
        debug("%s prefix: %s", self.__class__.__name__, prefix)
        return prefix

    @cached_property
    def datadir(self):
        """The datadir corresponding to the installation type of the currently running executable"""
        data_dir = self.prefix / "share"
        debug("%s datadir: %s", self.__class__.__name__, data_dir)
        return data_dir

    @cached_property
    def statedir(self):
        """The statedir where the device state files are stored

        The state directory for a user session service must be somewhere
        in the user's ``$HOME``, and a config file is a good place.
        """

        xdg_config_home = getenv("XDG_CONFIG_HOME")
        if xdg_config_home:  # neither None nor empty string
            config_dir = Path(xdg_config_home)
            debug(
                "%s XDG config dir from XDG_CONFIG_HOME variable: %s",
                self.__class__.__name__,
                config_dir,
            )
        else:
            config_dir = Path("~/.config").expanduser()
            debug(
                "%s XDG config dir default in ~: %s",
                self.__class__.__name__,
                config_dir,
            )

        state_dir = config_dir / const.PACKAGE / "state"
        debug("%s statedir: %s", self.__class__.__name__, state_dir)
        return state_dir

    @property
    @abc.abstractmethod
    def udev_rulesdir(self):
        pass  # AbstractDirs.udev_rulesdir


class GlobalDirs(AbstractDirs):
    pass  # class GlobalDirs


class AnyPrefixDirs(GlobalDirs):
    """Global install to ANY prefix.

    Should be useful for NixOS installs.
    """

    def __init__(self, chroot=None):
        debug("AnyPrefixDirs using chroot: %s", chroot)
        exe_path = exePath()
        debug("AnyPrefixDirs starting from exe path: %s", exe_path)
        if chroot is not None:
            exe_path_relative = exe_path.relative_to(Path(chroot))
            rooted_path = Path("/") / exe_path_relative
        else:
            rooted_path = exe_path
        assert rooted_path.parent.name == "bin"
        rooted_prefix = rooted_path.parent.parent
        self.PREFIX = rooted_prefix.resolve()
        super().__init__(chroot=chroot)

    @property
    def udev_rulesdir(self):
        return self.PREFIX / "lib/udev/rules.d"


class UsrDirs(GlobalDirs):
    """Global install to /usr"""

    PREFIX = Path("/usr")

    @property
    def udev_rulesdir(self):
        return Path("/usr/lib/udev/rules.d")


class UsrLocalDirs(GlobalDirs):
    """Global install to /usr/local"""

    PREFIX = Path("/usr/local")

    @property
    def udev_rulesdir(self):
        return Path("/usr/local/lib/udev/rules.d")


class HomeDirs(AbstractDirs):
    """User local install to $HOME/.local"""

    PREFIX = Path("~/.local").expanduser()

    @property
    def udev_rulesdir(self):
        return Path("/etc/udev/rules.d")


# The one instance of an AbstractDirs descendant class
__dir_instance = None


def init_dirs(chroot=None, force_prefix=False):
    global __dir_instance

    assert __dir_instance is None
    assert force_prefix is not None

    if force_prefix:
        __dir_instance = AnyPrefixDirs(chroot)
        info("Using dirs: %s", __dir_instance)
        return __dir_instance

    for cls in [UsrLocalDirs, UsrDirs, HomeDirs]:
        try:
            __dir_instance = cls(chroot)
            info("Using dirs: %s", __dir_instance)
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
