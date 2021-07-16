# socranop/installtool.py - post-install and pre-uninstall commands
#
# Implements post-install (install config files after having installed
# a wheel), and pre-uninstall (uninstall config files before
# uninstalling a wheel).
#
# Copyright (c) 2020,2021 Jim Ramsay <i.am@jimramsay.com>
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
import base64
import importlib
import io
import re
import sys
import time

from pathlib import Path
from pkg_resources import (
    resource_isdir,
    resource_string,
    resource_stream,
    resource_listdir,
)
from string import Template


import socranop
import socranop.constants as const
import socranop.common as common
from socranop.dirs import get_dirs, init_dirs


def print_step(tag, details, **printopts):
    """Standardized output for all install/uninstall actions"""
    print(f"  [{tag}] {details}", **printopts)


class Step:

    """\
    Allow easy printing of checks similar to the following:

        Some checks:
          [load] module pydbus: OK
          [load] module pydbus: ERROR
        Error: Cannot import module 'pydbus'. Make sure the 'pydbus' package is installed.
        Traceback (most recent call last):
          File ...
        ModuleNotFoundError: No module named 'pydbus'

    by writing the following three liner:

        with Step("load", "module pydbus",
                  error_msg="Cannot import module 'pydbus'. Make sure the 'pydbus' package is installed."):
            importlib.import_module("pydbus")  # import must work; discard retval
    """

    def __init__(self, tag, details, success_word=None, error_msg=None, max_attempts=0):
        super(Step, self).__init__()
        self.tag = tag
        self.details = details
        self.error_msg = error_msg
        self.success_word = success_word
        self.attempt = 0
        self.max_attempts = max_attempts

    @staticmethod
    def __step_start(tag, details):
        """Standardized output for all 2-part install/uninstall actions (start)"""
        print_step(tag, details, end=": ")

    @staticmethod
    def __step_success(success_word=None, postfix=None, **print_kwargs):
        """Standardized output for all 2-part install/uninstall actions (successful outcome)"""
        if postfix is None:
            print(success_word or "OK", **print_kwargs)
        else:
            print(success_word or "OK", postfix, **print_kwargs)

    @staticmethod
    def __step_failure(error_msg, postfix=None):
        """Standardized output for all 2-part install/uninstall actions (failure case)"""
        if postfix is None:
            print("ERROR")
        else:
            print("ERROR", postfix)
        print("Error:", error_msg)

    def set_success_word(self, success_word):
        self.success_word = success_word

    def try_again(self):
        self.attempt += 1
        if self.attempt > self.max_attempts:
            self.attempt = self.max_attempts
            raise Exception(
                f"exceeded maximum number of attempts ({self.max_attempts})"
            )
        self.__step_success(
            "not yet", postfix=f"(attempt {self.attempt}/{self.max_attempts})", end="\r"
        )
        self.__step_start(self.tag, self.details)
        time.sleep(1)

    def __enter__(self):
        self.__step_start(self.tag, self.details)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            if self.attempt == 0:
                self.__step_success(self.success_word)
            else:
                self.__step_success(
                    self.success_word,
                    postfix=f"(successful attempt {self.attempt}/{self.max_attempts})",
                )
        else:
            error_msg = self.error_msg or str(exc_value)
            if self.attempt == 0:
                self.__step_failure(error_msg)
            else:
                self.__step_failure(
                    error_msg,
                    postfix=f"(final attempt {self.attempt}/{self.max_attempts})",
                )
        return False


MAX_ATTEMPTS = 5


class ScriptCommand:
    """A single command which may need to be run in a sudo script

    These commands are to be collected into a shell script.  We do
    *not* run these commands directly via `subprocess.*`.

    Therefore, storing the command as a string containing a shell
    command is a good fit.
    """

    def __init__(self, cmd, skip_if=False, comment=None):
        common.debug("ScriptCommand.__init__", repr(cmd))
        assert type(cmd) == str
        self.cmd = cmd
        self.skip_if = skip_if
        self.comment = comment

    def write(self, file):
        """write this command to the script file"""
        file.write("\n")
        if self.comment:
            file.write(f"# {self.comment}\n")

        if self.skip_if:
            file.write("# [command skipped (not required)]\n")
            for line in self.cmd.splitlines():
                file.write(f"# {line}\n")
        else:
            file.write(self.cmd)
            file.write("\n")

    def __str__(self):
        return f"ScriptCommand({self.cmd!r})"


class SudoScript:
    """Gather shell commands which must be run by root/sudo into a script

    This script can then be presented to the user to audit and run.
    """

    def __init__(self):
        self.sudo_commands = []

    def add_cmd(self, cmd, skip_if=False, comment=None):
        """Add a command to the sudo script"""
        if skip_if:
            c = ScriptCommand(cmd, skip_if=True, comment=comment)
            common.debug(f"    [skip] {c.cmd!r}")
        else:
            c = ScriptCommand(cmd, skip_if=False, comment=comment)
            common.debug(f"    [q'ed] {c.cmd!r}")
        self.sudo_commands.append(c)

    def needs_to_run(self):
        """The sudo script only needs to run if there are commands in the script"""
        for c in self.sudo_commands:
            if c.skip_if:
                continue  # continue looking for a command to execute
            return True
        return False

    def write(self, file):
        """Write the sudo script to the script file"""
        file.write("#!/bin/sh\n")
        file.write(
            f"# This script contains commands which {const.BASE_EXE_INSTALLTOOL} could not run.\n"
        )
        file.write(
            "# You might have better luck running them manually, probably via sudo.\n"
        )
        if len(self.sudo_commands) > 0:
            for cmd in self.sudo_commands:
                cmd.write(file)
        else:
            file.write("\n# No commands to run.\n")

    def finalize(self, sudo_script):
        if (sudo_script is None) or (sudo_script in ["", "-"]):
            sudo_script_file = io.StringIO()
        else:
            sudo_script_file = open(sudo_script, "w")
            p = Path(sudo_script)
            p.chmod(0o0755)

        self.write(sudo_script_file)

        print()
        if not self.needs_to_run():
            print("No commands left over to run with sudo. Good.")
        elif isinstance(sudo_script_file, io.StringIO):
            print("You should probably run the following commands with sudo:")
            print("-" * 72)
            sys.stdout.write(sudo_script_file.getvalue())
            print("-" * 72)
        else:
            sudo_script_file.close()
            print(
                "You should probably run this script with sudo (example command below):"
            )
            print("-" * 72)
            sys.stdout.write(p.read_text())
            print("-" * 72)
            print("Suggested command:", "sudo", p.absolute())


SUDO_SCRIPT = SudoScript()


def findDataFiles(subdir):
    """Walk through data files in the socranop module's ``data`` subdir``"""

    result = {}
    modulepaths = socranop.__path__
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

    def __init__(self, dst, comment=None):
        super(AbstractFile, self).__init__()
        self.__dst = Path(dst)
        self.__comment = comment

    @property
    def comment(self):
        if self.__comment:
            return self.__comment
        else:
            return f"{self}"

    def __str__(self):
        return f"{self.__class__.__name__}:{self.dst}"

    @property
    def dst(self):
        """Destination Path() (not chrooted)"""
        return self.__dst

    @property
    def chroot_dst(self):
        """Destination Path() (chrooted if applicable)"""
        chroot = get_dirs().chroot
        if chroot:
            relpath = self.dst.relative_to("/")
            return chroot / relpath
        else:
            return self.dst

    @abc.abstractmethod
    def direct_install(self):
        """Install this file directly from Python code"""
        pass  # AbstractFile.direct_install()

    @abc.abstractmethod
    def shell_install(self):
        """Return shell command for the sudo script"""
        pass  # AbstractFile.shell_install()

    def _install(self):
        """Install this file (either directly from python or via sudo script)"""
        print_step("inst", self.dst)
        try:
            self.chroot_dst.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            self.direct_install()
            self.chroot_dst.chmod(mode=0o0644)
        except PermissionError:
            SUDO_SCRIPT.add_cmd(self.shell_install(), comment=self.comment)

    def _uninstall(self):
        """Uninstall this file (either directly from python or via sudo script)

        Like many other install/uninstall tools, we just remove the
        file and leave the directory tree around.
        """
        print_step("rm", self.dst)
        try:
            self.chroot_dst.unlink()
        except FileNotFoundError:
            pass  # we do not need to remove a non existant file
        except PermissionError:
            SUDO_SCRIPT.add_cmd(f"rm -f {self.dst}", comment=self.comment)


RESOURCE_MODULE = "socranop"


class ResourceFile(AbstractFile):
    """This destination file is written from a pkg_resource resource"""

    def __init__(self, dst, resource_name, comment=None):
        super(ResourceFile, self).__init__(dst, comment=comment)
        self.resource_name = resource_name

    def __str__(self):
        return f"{self.__class__.__name__}:{self.dst}:resource({self.resource_name})"

    def direct_install(self):
        self.chroot_dst.write_bytes(
            resource_string(RESOURCE_MODULE, self.resource_name)
        )

    def shell_install(self):
        first_line = f"base64>{self.dst}<<EOF\n"
        bio = io.BytesIO()
        res_stream = resource_stream(RESOURCE_MODULE, self.resource_name)
        base64.encode(res_stream, bio).decode("ascii")
        last_line = "EOF\n"
        return f"{first_line}{bio.getvalue()}{last_line}"


class StringToFile(AbstractFile):
    """This destination file is written from a string, no source file required"""

    def __init__(self, dst, content, comment=None):
        super(StringToFile, self).__init__(dst, comment=comment)

        self.content = content

    def direct_install(self):
        self.chroot_dst.write_text(self.content)

    def shell_install(self):
        lines = []
        lines.append(f"cat>{self.dst}<<EOF")
        lines.extend(self.content.splitlines())
        lines.append("EOF")
        return "\n".join(lines)


class TemplateFile(AbstractFile):
    """This destination file is a source file after string template processing"""

    def __init__(self, dst, resource_name, template_data=None, comment=None):
        super(TemplateFile, self).__init__(dst, comment=comment)

        if template_data is None:
            template_data = {}

        src_template = Template(
            resource_string(RESOURCE_MODULE, resource_name).decode("utf-8")
        )
        self.content = src_template.substitute(template_data)

        self.__resource_name = resource_name

    def __str__(self):
        return f"{self.__class__.__name__}:{self.dst}:resource({self.__resource_name})"

    def direct_install(self):
        self.chroot_dst.write_text(self.content)

    def shell_install(self):
        lines = []
        lines.append(f"cat>{self.dst}<<EOF")
        lines.extend(self.content.splitlines())
        lines.append("EOF")
        return "\n".join(lines)


class AbstractInstallTool(metaclass=abc.ABCMeta):
    """Things common to subsystem installtools"""

    def __init__(self, heading):
        self.heading = heading

    def _print_heading(self, reason):
        if self.heading is not None:
            print(f"{self.heading}: {reason}")

    @abc.abstractmethod
    def post_install(self):
        pass  # AbstractInstallTool.post_install()

    @abc.abstractmethod
    def pre_uninstall(self):
        pass  # AbstractInstallTool.pre_uninstall()


class CheckDependencies(AbstractInstallTool):
    """Make sure gi and the required typelibs are installed

    This checks that all imports of external Python libraries work
    and if they do not, attempts to show an error message useful
    to find the software package to install.

    Ideally, we want to detect missing package dependencies early
    during the setup stage, not at some time when the user is running
    the GUI or CLI programs.
    """

    def __init__(self):
        super(CheckDependencies, self).__init__(heading="Python library dependencies")

    def post_install(self):
        # If installing to a chroot environment, we cannot check what
        # is installed in that chroot environment, and therefore skip
        # the checks.
        if get_dirs().chroot:
            self._print_heading("Skipping")
            return

        self._print_heading("Checking")
        with Step(
            "load",
            "module gi",
            error_msg="Cannot import module 'gi'. The PyGI library must be installed from your distribution; usually called python-gi, python-gobject, python3-gobject, pygobject, or something similar.",
        ):
            importlib.import_module("gi")  # import must work; discard retval

        import gi

        for module, version in [
            ("GLib", None),
            ("Gtk", "3.0"),
            ("Gio", None),
            ("GUdev", "1.0"),
        ]:
            mod_name = f"gi.repository.{module}"

            if version:
                typelib = f"{module}-{version}.typelib"
            else:
                typelib = f"{module}-*.typelib"

            if version:
                with Step(
                    "find",
                    f"gi module {module} version {version}",
                    error_msg=f"Cannot find gi module '{mod_name}' in version {version}. Make sure the package providing the '{typelib}' file is installed with the required dependencies.",
                ):
                    gi.require_version(module, version)

            with Step(
                "load",
                f"gi module {module}",
                error_msg=f"Cannot import gi module '{mod_name}'. Make sure the package providing the '{typelib}' file is installed with its required dependencies.",
            ):
                importlib.import_module(mod_name)  # import must work; discard retval

        # pydbus internally requires gi and GLib, Gio, GObject
        with Step(
            "load",
            "module pydbus",
            error_msg="Cannot import module 'pydbus'. Make sure the 'pydbus' package is installed.",
        ):
            importlib.import_module("pydbus")  # import must work; discard retval

        with Step(
            "load",
            "module usb.core",
            error_msg="Cannot import module 'usb.core'. Make sure the 'pyusb' package is installed.",
        ):
            importlib.import_module("usb.core")  # import must work; discard retval

        import usb.core

        # check that finding any USB device works
        with Step(
            "check",
            "finding any usb device",
            error_msg="Have not found a single USB device. Something is broken here.",
        ):
            usb_devices = usb.core.find(find_all=True)
            if len(list(usb_devices)) == 0:
                raise ValueError("No USB devices found")

        self._print_heading("OK")

    def pre_uninstall(self):
        pass  # CheckDependencies.pre_uninstall() does not need to do anything


class FileInstallTool(AbstractInstallTool):
    """A subsystem which needs to install/uninstall a number of files"""

    @staticmethod
    def int_as_str(thing):
        """Help sorting numbers

        Help with sorting numbers by converting every integer to a fixed
        length string starting with leading zeros to make alphabetical
        sorting sort numerically.
        """
        try:
            i = int(thing)
            return "%08d" % i
        except ValueError:
            return thing

    # Help with sorting numbers inside path elements
    destfile_key_re = re.compile(r"((?<=\d)(?=\D)|(?<=\D)(?=\d))")

    @staticmethod
    def destfile_key(file):
        """Convert a Path() to something which sorts as a alphabetical/numerical hybrid"""
        path = file.dst
        return tuple(
            tuple(
                map(
                    FileInstallTool.int_as_str, FileInstallTool.destfile_key_re.split(s)
                )
            )
            for s in path.parts
        )

    def __init__(self, heading):
        super(FileInstallTool, self).__init__(heading)
        self.files = []

    def add_file(self, file):
        common.debug("Adding file", self, file)
        self.files.append(file)

    def _do_install(self):
        for file in sorted(self.files, key=FileInstallTool.destfile_key):
            file._install()

    def _do_uninstall(self):
        for file in sorted(self.files, key=FileInstallTool.destfile_key, reverse=True):
            file._uninstall()

    def post_install(self):
        self._print_heading("Installing files")
        self._do_install()
        self._print_heading("Install completed")

    def pre_uninstall(self):
        self._print_heading("Uninstalling files")
        self._do_uninstall()
        self._print_heading("Uninstall completed")


class ResourceInstallTool(FileInstallTool):
    """A subsystem which iterates through resources in data/"""

    def __init__(self, heading):
        super(ResourceInstallTool, self).__init__(heading)

    def walk_resources(self, resdir):
        common.debug("walk_through_data_files", self, resdir)
        assert resource_isdir(RESOURCE_MODULE, "data")

        def walk_resource_subdir(subdir):
            full_subdir = f"data/{subdir}"
            assert resource_isdir(RESOURCE_MODULE, full_subdir)
            for name in resource_listdir(RESOURCE_MODULE, full_subdir):
                full_name = f"{full_subdir}/{name}"
                common.debug("res fullname", full_name)
                if resource_isdir(RESOURCE_MODULE, full_name):
                    walk_resource_subdir(f"{subdir}/{name}")
                else:
                    if full_name.endswith("~"):
                        continue  # ignore editor backup files
                    self.add_resource(full_name)

        walk_resource_subdir(resdir)

    @abc.abstractmethod
    def add_resource(self, fullname):
        """Examine src file and decide what to do about it

        Examine the given source resource ``fullname`` and then
        decide whether to

          * ``self.add_file()`` an instance of ``ResourceToFile``
          * ``raise UnhandledResource(src)``
        """
        pass  # ResourceInstallTool.add_resource()


class UnhandledResource(Exception):
    """Unhandled resource encountered while walking through resource tree"""

    pass  # class UnhandledResource


class DBusInstallTool(ResourceInstallTool):
    """Subsystem dealing with the D-Bus configuration files"""

    def __init__(self, no_launch):
        super(DBusInstallTool, self).__init__(heading="Dbus service")
        self.no_launch = no_launch
        self.walk_resources("dbus-1")
        self.__session_bus = None

    def _service(self, service_name):
        if self.__session_bus is None:
            import pydbus

            self.__session_bus = pydbus.SessionBus()
        return self.__session_bus.get(service_name)

    def add_resource(self, fullname):
        common.debug("add_resource", self, fullname)
        if fullname.endswith(".service"):
            dirs = get_dirs()
            templateData = {
                "dbus_service_bin": str(dirs.serviceExePath),
                "busname": const.BUSNAME,
            }

            service_dir = dirs.datadir / "dbus-1/services"
            service_dst = service_dir / f"{const.BUSNAME}.service"

            service_file = TemplateFile(
                service_dst, fullname, template_data=templateData
            )
            self.add_file(service_file)
        else:
            raise UnhandledResource(fullname)

    def post_install(self):
        self._print_heading("Configuring")
        self.shutdown_service("Stopping old service")

        super(DBusInstallTool, self)._do_install()

        self.verify_install()

        self._print_heading("Complete")

    def shutdown_service(self, reason):
        if self.no_launch:
            common.debug("Not shutting down old service (no_launch is set)")
            return

        dbus_service = self._service(".DBus")
        if not dbus_service.NameHasOwner(const.BUSNAME):
            common.debug("D-Bus service not running")
        else:
            service = self._service(const.BUSNAME)
            service_version = service.version
            with Step(
                "stop",
                f"Shutting down running service version {service_version}",
                max_attempts=MAX_ATTEMPTS,
            ) as step:
                service.Shutdown()
                # Wait until the shutdown clears the service off the bus
                while dbus_service.NameHasOwner(const.BUSNAME):
                    step.try_again()

    def verify_install(self, force=False):
        if self.no_launch and not force:
            common.debug("no_launch is set; not verifying our dbus service")
            return

        dbus_service = self._service(".DBus")
        with Step("verify", "Reload dbus to register the new service"):
            # An explicit reload is required in case dbus isn't smart enough to see
            # us drop in the service file (dbus-broker, for example, if we just
            # created ~/.local/share/dbus-1/services)
            dbus_service.ReloadConfig()

        with Step(
            "verify",
            "Checking for registered service",
            error_msg=f"The dbus service we just installed has not yet been detected after {MAX_ATTEMPTS}s. You may need to restart your dbus session (for example, by logging out and back in to your desktop).",
            max_attempts=MAX_ATTEMPTS,
        ) as step:
            while const.BUSNAME not in dbus_service.ListActivatableNames():
                step.try_again()

        # Just using the service proves auto-start works:
        with Step("verify", "Starting D-Bus service") as step:
            our_service = self._service(const.BUSNAME)
            service_version = our_service.version
            step.set_success_word(service_version)

        with Step("verify", "Installtool    version", success_word=const.VERSION):
            pass

        # TODO: Compare versions?  Fail if there's a mismatch?

        # Shut down the service now, in case there are other steps
        # that need to take place (i.e. udev permissions) before the
        # service can really be used.
        with Step("verify", "Shutting down session D-Bus service"):
            our_service.Shutdown()

    def pre_uninstall(self):
        self._print_heading("Configuring")
        self.shutdown_service("Stopping service")
        super(DBusInstallTool, self)._do_uninstall()
        self._print_heading("Complete")


class BashCompletionInstallTool(ResourceInstallTool):
    """Subsystem dealing with bash-completion files"""

    def __init__(self):
        super(BashCompletionInstallTool, self).__init__(heading="Bash completion")

        # TODO: What about /usr/local?
        self.bc_dir = get_dirs().datadir / "bash-completion" / "completions"

        self.walk_resources("bash-completion")

    def add_resource(self, fullname):
        src = Path(fullname)
        dst = self.bc_dir / src.name
        self.add_file(ResourceFile(dst, fullname))


class ManpageInstallTool(ResourceInstallTool):
    """Subsystem dealing with man pages"""

    def __init__(self):
        super(ManpageInstallTool, self).__init__(heading="Man pages")
        self.template_data = {
            "PACKAGE": const.PACKAGE,
            "VERSION": const.VERSION,
            "APPLICATION_ID": const.APPLICATION_ID,
            "datadir": get_dirs().datadir,
            "socranopdir": socranop.__path__[0],
        }
        self.walk_resources("man")

    def mandir(self):
        dirs = get_dirs()
        return dirs.datadir / "man"

    def add_resource(self, fullname):
        mansrc = Path(fullname)
        if fullname.endswith(".1"):
            mandst = self.mandir() / "man1" / mansrc.name
            manfile = TemplateFile(mandst, fullname, template_data=self.template_data)
            self.add_file(manfile)
        else:
            raise UnhandledResource(fullname)


class XDGDesktopInstallTool(ResourceInstallTool):
    """Subsystem dealing with the XDG desktop and icon files"""

    # FIXME05: Find out whether `xdg-desktop-menu` and `xdg-desktop-icon`
    #          must be run after all. Fedora Packaging docs suggest so.

    def __init__(self):
        super(XDGDesktopInstallTool, self).__init__("XDG application launcher")
        self.walk_resources("xdg")

    def add_resource(self, fullname):
        if fullname.endswith(".desktop"):
            dirs = get_dirs()
            applications_dir = dirs.datadir / "applications"
            dst = applications_dir / f"{const.APPLICATION_ID}.desktop"
            templateData = {
                "gui_bin": dirs.guiExePath,
                "APPLICATION_ID": const.APPLICATION_ID,
            }
            self.add_file(TemplateFile(dst, fullname, templateData))
        elif fullname.endswith(".png"):
            m = len(fullname) - 4
            n = fullname.rindex(".", 0, m) + 1
            size = int(fullname[n:m], 10)
            dst = self.icondir(size) / f"{const.APPLICATION_ID}.png"
            self.add_file(ResourceFile(dst, fullname))
        elif fullname.endswith(".svg"):
            dst = self.icondir() / f"{const.APPLICATION_ID}.svg"
            self.add_file(ResourceFile(dst, fullname))
        else:
            raise UnhandledResource(fullname)

    def icondir(self, size=None):
        dirs = get_dirs()
        if size is None:
            return dirs.datadir / "icons/hicolor/scalable/apps"
        else:
            return dirs.datadir / f"icons/hicolor/{size}x{size}/apps"


class UdevRulesInstallTool(FileInstallTool):
    """Subsystem dealing with the udev rules"""

    # FIXME: udev is Linux-only. What about non-Linux systems?

    def __init__(self):
        super(UdevRulesInstallTool, self).__init__(heading="Udev rules")

        # Generate the file contents in Python so we can install it
        # from Python in case we do have write permissions.
        lines = [
            "# Soundcraft Notepad series mixers with audio routing controlled by USB"
        ]
        for product_id in const.PY_LIST_OF_PRODUCT_IDS:
            lines.append(
                f'ACTION=="add", SUBSYSTEM=="usb", ATTRS{{idVendor}}=="{const.VENDOR_ID_HARMAN:04x}", ATTRS{{idProduct}}=="{product_id:04x}", TAG+="uaccess"'
            )

        self.udev_rules_content = "".join([f"{line}\n" for line in lines])
        self.udev_rules_dst = get_dirs().udev_rulesdir / f"70-{const.PACKAGE}.rules"
        self.add_file(
            StringToFile(
                self.udev_rules_dst,
                self.udev_rules_content,
                comment="udev rules allowing non-root access to the USB device",
            )
        )

    def emit_code_for_rule_change(self, skip_if):
        # udev is supposed to have been picking up changed rules "for
        # years" (relative to 2016), so manually triggering a reload
        # does not appear to be called for any more.
        #
        # SUDO_SCRIPT.add_cmd(
        #     "udevadm control --reload",
        #     skip_if=skip_if,
        #     comment="Make udev take notice of the updated set of udev rules",
        # )

        # FIXME: In case installtool is running as root, run udevadm directly.

        sh_list_of_product_ids = " ".join(
            ["%04x" % n for n in const.PY_LIST_OF_PRODUCT_IDS]
        )
        SUDO_SCRIPT.add_cmd(
            f"""\
sleep 4   # wait until udev should have noticed the new rules
for product_id in {sh_list_of_product_ids}
do
    udevadm trigger --verbose \\
        --action=add --subsystem-match=usb \\
        --attr-match=idVendor={const.VENDOR_ID_HARMAN:04x} --attr-match=idProduct=${{product_id}}
done""",
            skip_if=skip_if,
            comment="Trigger udev rules which run when adding existing mixer devices",
        )

    def post_install(self):
        # Populate with the files installed pre installation
        old_content = {}
        if self.udev_rules_dst.exists():
            old_content[self.udev_rules_dst] = self.udev_rules_dst.read_text()

        super(UdevRulesInstallTool, self).post_install()

        # Populate with the files which we (should/will) have installed
        new_content = {}
        new_content[self.udev_rules_dst] = self.udev_rules_content

        if common.VERBOSE:
            from pprint import pprint

            print("OLD")
            pprint(old_content)
            print("NEW")
            pprint(new_content)

        self.emit_code_for_rule_change(skip_if=(new_content == old_content))

    def pre_uninstall(self):
        # FIXME05: Do we even want to uninstall the udev rules if it
        #          is in /etc/udev/rules.d for a $HOME/.local install?
        #          The next install will just need sudo access again
        #          to install it again.

        old_content = {}
        if self.udev_rules_dst.exists():
            old_content[self.udev_rules_dst] = self.udev_rules_dst.read_text()

        super(UdevRulesInstallTool, self).pre_uninstall()

        new_content = dict(old_content)
        if self.udev_rules_dst in new_content:
            del new_content[self.udev_rules_dst]

        if common.VERBOSE:
            from pprint import pprint

            print("OLD")
            pprint(old_content)
            print("NEW")
            pprint(new_content)

        self.emit_code_for_rule_change(skip_if=(new_content == old_content))


class InstallToolEverything(AbstractInstallTool):
    """Groups all subsystem installtools"""

    def __init__(self):
        super(InstallToolEverything, self).__init__(heading=None)
        self.everything = []

    def add(self, thing):
        self.everything.append(thing)

    def post_install(self):
        print("Socranop Installation")
        print("=====================")
        print()
        for thing in self.everything:
            thing.post_install()
        print()
        print(f"Socranop installation has completed successfully.")

    def post_install_footer(self):
        print()
        print(
            f"Finally, run `{const.BASE_EXE_GUI}` or `{const.BASE_EXE_CLI}` as a regular user."
        )

    def pre_uninstall(self):
        print("Socranop Uninstallation Preparation")
        print("===================================")
        print()
        for thing in reversed(self.everything):
            thing.pre_uninstall()
        print()
        print(f"Socranop uninstallation preparation has completed successfully.")

    def pre_uninstall_footer(self):
        print()
        print(f"Finally, run `pip uninstall socranop` to complete uninstallation.")


def main():
    # Caution: If you change the command line parser in any way,
    #          update the man pages and bash completions accordingly.

    parser = argparse.ArgumentParser(
        description=f"hook {const.PACKAGE} into the system post-install (or do the reverse)"
    )
    common.parser_args(parser)

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

    parser.add_argument(
        "--sudo-script",
        metavar="FILENAME",
        help="write the script of sudo commands to the given FILENAME",
        default=None,
    )

    args = parser.parse_args()
    common.VERBOSE = args.verbose
    if args.chroot:
        # If chroot is given, the service file is installed inside the chroot
        # and starting/stopping the service does not make sense.
        args.no_launch = True

    if args.chroot and args.sudo_script:
        print("Error: argument --chroot and --sudo-script are mutually exclusive.")
        sys.exit(2)

    if args.chroot:
        print("Using chroot", args.chroot)

    # Initialize the dirs object with the chroot given so that later
    # calls to get_dirs() will yield an object which uses the same
    # chroot value.
    dirs = init_dirs(chroot=args.chroot)
    common.debug("Using dirs", dirs)

    everything = InstallToolEverything()
    everything.add(CheckDependencies())
    everything.add(BashCompletionInstallTool())
    everything.add(DBusInstallTool(no_launch=args.no_launch))
    everything.add(ManpageInstallTool())
    everything.add(XDGDesktopInstallTool())
    everything.add(UdevRulesInstallTool())

    if args.post_install:
        everything.post_install()
    elif args.pre_uninstall:
        everything.pre_uninstall()

    if args.chroot:
        return

    SUDO_SCRIPT.finalize(args.sudo_script)

    if args.post_install:
        everything.post_install_footer()
    elif args.pre_uninstall:
        everything.pre_uninstall_footer()
