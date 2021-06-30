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


import sys

from os import getenv
from pathlib import Path

import soundcraft.constants as const


class _Dirs:

    """Detect installation type and determine adequate directories

    Supported installation types are:

      * global installation to ``/usr/``
      * global installation to ``/usr/local/``
      * local installation to ``$HOME/.local/``
    """

    def __init__(self):
        super(_Dirs, self).__init__()

        self._prefix = None
        self._statedir = None

        # print(self)

    def __str__(self):
        props = ["prefix", "datadir", "statedir"]
        ps = ", ".join([("%s=%r" % (p, str(getattr(self, p)))) for p in props])
        return f"{self.__class__.__name__}({ps})"

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
        return self.exePath.parent / const.BASE_EXE_GUI

    @property
    def serviceExePath(self):
        """Full path to the service script executable"""
        return self.exePath.parent / const.BASE_EXE_SERVICE

    def __init_prefix(self):
        for prefix in [
            Path("/usr/local"),
            Path("/usr"),
            Path("~/.local").expanduser(),
        ]:
            for sx_dir in ["bin", "sbin", "libexec"]:
                for sx in [
                    const.BASE_EXE_CLI,
                    const.BASE_EXE_GUI,
                    const.BASE_EXE_SERVICE,
                    const.BASE_EXE_INSTALLTOOL,
                ]:
                    sx_path = prefix / sx_dir / sx
                    print("sx_path", sx_path)
                    if sx_path == self.exePath:
                        return prefix
                    try:
                        self.exePath.relative_to(prefix)  # ignore result

                        # If this is, say,
                        # ``/home/user/.local/share/virtualenvs/soundcraft-utils-ABCDEFG/bin/soundcraft_installtool``,
                        # then the D-Bus and XDG config can either go into
                        # ``/home/user/.local/share/virtualenvs/soundcraft-utils-ABCDEFG/share/``
                        # and be ignored, or go into
                        # ``/home/user/.local/share/`` and work. We choose
                        # the latter.
                        return prefix
                    except ValueError:
                        pass  # self.exePath is not a subdir of prefix
        raise ValueError(f"Exe path is not supported: {self.exePath!r}")

    @property
    def prefix(self):
        """The prefix corresponding to the installation type of the currently running executable"""
        if self._prefix is None:
            self._prefix = self.__init_prefix()
        return self._prefix

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


# The one instance of a _Dirs class object
__dir_instance = None


def __init_dirs():
    global __dir_instance

    assert __dir_instance is None
    __dir_instance = _Dirs()


def get_dirs():
    global __dir_instance

    if __dir_instance is None:
        __init_dirs()

    return __dir_instance
