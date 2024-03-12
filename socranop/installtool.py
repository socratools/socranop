# socranop/installtool.py - post-install and pre-uninstall commands
#
# Implements post-pip-install (install config files after having
# installed a wheel), and pre-pip-uninstall (uninstall config files
# before uninstalling a wheel), and package-build-install (the for
# install part of building a package).
#
# Copyright (c) 2020,2021 Jim Ramsay <i.am@jimramsay.com>
# Copyright (c) 2020,2021,2023,2024 Hans Ulrich Niedermann <hun@n-dimensional.de>
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
import functools
import importlib
import importlib.resources
import io
import re
import sys
import time

from pathlib import Path
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
        assert isinstance(cmd, str)
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

    def finalize(self, sudo_script, dry_run):
        if (sudo_script is None) or (sudo_script in ["", "-"]):
            sudo_script_file = io.StringIO()
        elif dry_run:
            print(f"would write sudo script to {sudo_script}")
            sudo_script_file = io.StringIO()
        else:
            sudo_script_file = open(sudo_script, "w")
            p = Path(sudo_script)
            p.chmod(0o0755)

        self.write(sudo_script_file)

        print()
        # TODO: Could be worded more nicely with dry_run==True
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
            print("Suggested command:", "sudo", "sh", p.absolute())


SUDO_SCRIPT = SudoScript()


class AbstractFile(metaclass=abc.ABCMeta):
    """Common behavior for different types of files defined as subclasses"""

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

    def install(self, dry_run):
        """Install this file (either directly from python or via sudo script)"""
        if dry_run:
            print_step("would inst", self.dst)
            return

        try:
            print_step("inst", self.dst)
            self.chroot_dst.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            self.direct_install()
            self.chroot_dst.chmod(mode=0o0644)
        except PermissionError:
            print_step("sudo inst", self.dst)
            SUDO_SCRIPT.add_cmd(self.shell_install(), comment=self.comment)

    def uninstall(self, dry_run):
        """Uninstall this file (either directly from python or via sudo script)

        Like many other install/uninstall tools, we just remove the
        file and leave the directory tree around.
        """
        if dry_run:
            print_step("would rm", self.dst)
            return

        if not self.chroot_dst.exists():
            print_step("--", self.dst)
            return

        try:
            print_step("rm", self.dst)
            self.chroot_dst.unlink(missing_ok=True)
        except PermissionError:
            print_step("sudo rm", self.dst)
            SUDO_SCRIPT.add_cmd(f"rm -f {self.dst}", comment=self.comment)


RESOURCE_MODULE = "socranop"


class ResourceFile(AbstractFile):
    """This destination file is written from a pkg_resource resource"""

    def __init__(self, dst, resource_entry, comment=None):
        super(ResourceFile, self).__init__(dst, comment=comment)
        self.resource_entry = resource_entry

    def __str__(self):
        return f"{self.__class__.__name__}:{self.dst}:resource({self.resource_entry})"

    def direct_install(self):
        self.chroot_dst.write_bytes(self.resource_entry.read_bytes())

    def shell_install(self):
        first_line = f"base64>{self.dst}<<EOF\n"
        bio = io.BytesIO()
        res_bytes = self.resource_entry.read_binary()
        bio.write(base64.encodebytes(res_bytes))
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


class FilesToDelete:
    """Collect all files related to the install tool.

    Collecting a list of all files related to the install tool helps
    when building a binary OS package (*.rpm, *.deb, etc.), allowing
    to easily remove those files after use at package build time and
    before before shipping the files in the package.
    """

    def __init__(self):
        self.files = set()

    @property
    def chroot(self):
        return get_dirs().chroot

    def add(self, fpath: Path):
        abs_name = fpath.absolute()
        if self.chroot is None:
            return
        # print("self.chroot", self.chroot)
        if not abs_name.is_relative_to(self.chroot):
            return
        self.files.add(abs_name)

    def remove_all(self):
        if not self.chroot:
            return
        if self.chroot.samefile("/"):
            return
        print()
        print(
            f"Removing all installed files related to {const.BASE_EXE_INSTALLTOOL} from chroot {self.chroot}:"
        )

        for e in sorted(list(self.files), reverse=True):
            unchrooted_e = e.relative_to(self.chroot)
            if e.is_dir():
                print(f"  rmdir {unchrooted_e!s}")
                e.rmdir()
            else:
                print(f"  rm    {unchrooted_e!s}")
                e.unlink()

        print(
            f"All installed files related to {const.BASE_EXE_INSTALLTOOL} have been removed."
        )


global files_to_delete
files_to_delete = None


class TemplateFile(AbstractFile):
    """This destination file is a source file after string template processing"""

    def __init__(self, dst, resource_entry, template_data=None, comment=None):
        super(TemplateFile, self).__init__(dst, comment=comment)

        if template_data is None:
            template_data = {}

        src_template = Template(resource_entry.read_text(encoding="utf-8"))
        self.content = src_template.substitute(template_data)

        self.__resource_entry = resource_entry

    def __str__(self):
        return (
            f"{self.__class__.__name__}:{self.dst}:resource({self.__resource_entry!s})"
        )

    def direct_install(self):
        self.chroot_dst.write_text(self.content)

    def shell_install(self):
        lines = []
        lines.append(f"cat>{self.dst}<<EOF")
        lines.extend(self.content.splitlines())
        lines.append("EOF")
        return "\n".join(lines)


class AbstractInstallTool(metaclass=abc.ABCMeta):
    """Things common to subsystem InstallTool classes"""

    def __init__(self, dry_run, heading):
        self.__dry_run = dry_run
        self.__heading = heading

    def _print_heading(self, reason):
        if self.__heading is not None:
            print(f"{self.__heading}: {reason}")

    @property
    def dry_run(self):
        return self.__dry_run

    @abc.abstractmethod
    def post_pip_install(self):
        pass  # AbstractInstallTool.post_pip_install()

    @abc.abstractmethod
    def pre_pip_uninstall(self):
        pass  # AbstractInstallTool.pre_pip_uninstall()

    @abc.abstractmethod
    def package_build_install(self):
        pass  # AbstractInstallTool.package_build_install()


class CheckDependencies(AbstractInstallTool):
    """Make sure gi and the required typelibs are installed

    This checks that all imports of external Python libraries work
    and if they do not, attempts to show an error message helpful
    for finding the software package to install.

    Ideally, we want to detect missing package dependencies early
    during the setup stage, not at some time when the user is running
    the GUI or CLI programs.
    """

    def __init__(self, dry_run):
        super(CheckDependencies, self).__init__(
            dry_run=dry_run, heading="Python library dependencies"
        )

    def post_pip_install(self):
        # If installing to a chroot environment, we cannot check what
        # is installed in that chroot environment, and therefore skip
        # the checks.
        if get_dirs().chroot:
            self._print_heading("Skipping (due to chroot environment)")
            return

        if self.dry_run:
            self._print_heading("Would import gi")
            self._print_heading("Would import gi.repository.GLib")
            self._print_heading("Would import gi.repository.Gtk version 3.0")
            self._print_heading("Would import gi.repository.Gio")
            self._print_heading("Would import gi.repository.GUdev version 1.0")
            self._print_heading("Would import pydbus")
            self._print_heading("Would import usb.core")
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

    def pre_pip_uninstall(self):
        pass  # CheckDependencies.pre_pip_uninstall() does not need to do anything

    def package_build_install(self):
        pass  # CheckDependencies.package_build_install() does not need to do anything


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

    def __init__(self, dry_run, heading):
        super(FileInstallTool, self).__init__(dry_run=dry_run, heading=heading)
        self.files = []

    def add_file(self, file):
        common.debug("Adding file", self, file)
        self.files.append(file)

    def do_install_files(self):
        self._print_heading("Installing files")
        for file in sorted(self.files, key=FileInstallTool.destfile_key):
            file.install(self.dry_run)
        self._print_heading("Install completed")

    def do_uninstall_files(self):
        self._print_heading("Uninstalling files")
        for file in sorted(self.files, key=FileInstallTool.destfile_key, reverse=True):
            file.uninstall(self.dry_run)
        self._print_heading("Uninstall completed")

    def post_pip_install(self):
        self.do_install_files()

    def pre_pip_uninstall(self):
        self.do_uninstall_files()

    def package_build_install(self):
        self.do_install_files()


class ResourceInstallTool(FileInstallTool):
    """A subsystem which iterates through resource files in data/"""

    def __init__(self, dry_run, heading):
        super(ResourceInstallTool, self).__init__(dry_run, heading)

    def walk_resources(self, res_subdir: str):
        common.debug("walk_resources", self, res_subdir)

        res_data = importlib.resources.files(RESOURCE_MODULE) / "data"

        global files_to_delete
        files_to_delete.add(res_data)

        td = res_data / res_subdir

        def walk_resource_subdir(topdir):
            assert topdir.is_dir()
            global files_to_delete
            files_to_delete.add(topdir)
            for entry in topdir.iterdir():
                full_name = entry.absolute()
                common.debug(f"entry {entry} res fullname {full_name}")
                if entry.is_dir():
                    walk_resource_subdir(entry)
                else:
                    if entry.name.endswith("~"):
                        continue  # ignore editor backup files
                    self.add_resource(entry)
                    files_to_delete.add(entry)

        walk_resource_subdir(td)

    @abc.abstractmethod
    def add_resource(self, resource_entry):
        """Examine source file and decide what to do about it

        Examine the given source resource ``entry`` and then
        decide whether to

          * ``self.add_file()`` an instance of ``ResourceToFile``
          * ``raise UnhandledResource(src)``
        """
        pass  # ResourceInstallTool.add_resource()


class UnhandledResource(Exception):
    """Unhandled resource encountered while walking through resource tree"""

    pass  # class UnhandledResource


class DBusInstallTool(ResourceInstallTool):
    """Deal with D-Bus .service file and the service it defines"""

    # FIXME: Only test start the service on unprivileged post-pip-install?
    #        We *are* shutting down the service after testing in any case...

    def __init__(self, dry_run, no_launch):
        super(DBusInstallTool, self).__init__(dry_run=dry_run, heading="Dbus service")
        self.no_launch = no_launch
        self.walk_resources("dbus-1")

    @functools.cached_property
    def _session_bus(self):
        import pydbus

        return pydbus.SessionBus()

    def _service(self, service_name):
        return self._session_bus.get(service_name)

    def add_resource(self, resource_entry):
        common.debug("add_resource", self, resource_entry)
        if resource_entry.name.endswith(".service"):
            dirs = get_dirs()
            templateData = {
                "dbus_service_bin": str(dirs.serviceExePath),
                "busname": const.BUSNAME,
            }

            service_dir = dirs.datadir / "dbus-1/services"
            service_dst = service_dir / f"{const.BUSNAME}.service"

            service_file = TemplateFile(
                service_dst, resource_entry, template_data=templateData
            )
            self.add_file(service_file)
        else:
            raise UnhandledResource(resource_entry)

    def post_pip_install(self):
        self._print_heading("Configuring")
        self._shutdown_service("Stopping old service")

        super(DBusInstallTool, self).do_install_files()

        self._verify_install()

        self._print_heading("Complete")

    def _shutdown_service(self, reason):
        if self.no_launch:
            common.debug("no_launch is set; not shutting down old service")
            return

        if self.dry_run:
            with Step("would stop", "would shut down running service"):
                pass
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

    def _verify_install(self):
        if self.no_launch:
            common.debug("no_launch is set; not verifying our dbus service")
            return

        if self.dry_run:
            with Step("would start", "would start and check the service"):
                pass
            return

        dbus_service = self._service(".DBus")
        with Step("verify", "Reload D-Bus to register the new service"):
            # An explicit reload is required in case D-Bus isn't smart
            # enough to observe us dropping the service file into the
            # folder (dbus-broker, for example, if we just created
            # ~/.local/share/dbus-1/services)
            dbus_service.ReloadConfig()

        with Step(
            "verify",
            "Checking for registered service",
            error_msg=f"The D-Bus service we just installed has not yet been detected after {MAX_ATTEMPTS}s. You may need to restart your D-Bus session (for example, by logging out and back in to your desktop).",
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

    def pre_pip_uninstall(self):
        self._print_heading("Configuring")
        self._shutdown_service("Stopping service")
        super(DBusInstallTool, self).do_uninstall_files()
        self._print_heading("Complete")


class BashCompletionInstallTool(ResourceInstallTool):
    """Deal with bash-completion files"""

    def __init__(self, dry_run):
        super(BashCompletionInstallTool, self).__init__(
            dry_run=dry_run, heading="Bash completion"
        )

        # TODO: What about /usr/local?
        self.bc_dir = get_dirs().datadir / "bash-completion" / "completions"

        self.walk_resources("bash-completion")

    def add_resource(self, resource_entry):
        dst = self.bc_dir / resource_entry.name
        rf = ResourceFile(dst, resource_entry)
        if resource_entry.name == const.BASE_EXE_INSTALLTOOL:
            global files_to_delete
            files_to_delete.add(resource_entry)
            files_to_delete.add(rf.chroot_dst)
        self.add_file(rf)


class ManpageInstallTool(ResourceInstallTool):
    """Deal with man pages"""

    def __init__(self, dry_run):
        super(ManpageInstallTool, self).__init__(dry_run=dry_run, heading="Man pages")
        dirs = get_dirs()
        self.template_data = {
            "PACKAGE": const.PACKAGE,
            "VERSION": const.VERSION,
            "APPLICATION_ID": const.APPLICATION_ID,
            "datadir": dirs.datadir,
            "socranopdir": dirs.remove_chroot(Path(socranop.__path__[0])),
        }
        self.walk_resources("man")

    def _mandir(self):
        dirs = get_dirs()
        return dirs.datadir / "man"

    def add_resource(self, resource_entry):
        rexpr = re.compile(r".*\.(?P<section>[1-9])")
        m = rexpr.fullmatch(resource_entry.name)
        if m:
            section = m.group("section")
            mandst = self._mandir() / f"man{section}" / resource_entry.name
            manfile = TemplateFile(
                mandst, resource_entry, template_data=self.template_data
            )
            if mandst.stem == const.BASE_EXE_INSTALLTOOL:
                global files_to_delete
                files_to_delete.add(manfile.chroot_dst)
                files_to_delete.add(manfile.chroot_dst.parent)
            self.add_file(manfile)
        else:
            raise UnhandledResource(resource_entry)


class XDGDesktopInstallTool(ResourceInstallTool):
    """Deal with the XDG .desktop and PNG/SVG icon files"""

    # FIXME05: Find out whether `xdg-desktop-menu` and `xdg-desktop-icon`
    #          must be run after all. Fedora Packaging docs suggest so.

    def __init__(self, dry_run):
        super(XDGDesktopInstallTool, self).__init__(
            dry_run=dry_run, heading="XDG application launcher"
        )
        self.walk_resources("xdg")

    def add_resource(self, resource_entry):
        if resource_entry.name.endswith(".desktop"):
            dirs = get_dirs()
            applications_dir = dirs.datadir / "applications"
            dst = applications_dir / f"{const.APPLICATION_ID}.desktop"
            templateData = {
                "gui_bin": dirs.guiExePath,
                "APPLICATION_ID": const.APPLICATION_ID,
            }
            self.add_file(TemplateFile(dst, resource_entry, templateData))
        elif resource_entry.name.endswith(".png"):
            m = len(resource_entry.name) - 4
            n = resource_entry.name.rindex(".", 0, m) + 1
            size = int(resource_entry.name[n:m], 10)
            dst = self._icondir(size) / f"{const.APPLICATION_ID}.png"
            self.add_file(ResourceFile(dst, resource_entry))
        elif resource_entry.name.endswith(".svg"):
            dst = self._icondir() / f"{const.APPLICATION_ID}.svg"
            self.add_file(ResourceFile(dst, resource_entry))
        else:
            raise UnhandledResource(resource_entry)

    def _icondir(self, size=None):
        dirs = get_dirs()
        if size is None:
            return dirs.datadir / "icons/hicolor/scalable/apps"
        else:
            return dirs.datadir / f"icons/hicolor/{size}x{size}/apps"


class UdevRulesInstallTool(FileInstallTool):
    """Subsystem dealing with the udev rules

    Create and install a udev rules file, and call "udevadm trigger"
    for each supported device.

    We *could* make the udev rules file a static data file to copy,
    but as long as it needs a special destination outside of the
    ${prefix}/share data directory, we cannot use setuptools' handling
    of data files to help us anyway.
    """

    # FIXME: udev is Linux-only. What about non-Linux systems?

    def __init__(self, dry_run):
        super(UdevRulesInstallTool, self).__init__(
            dry_run=dry_run, heading="Udev rules"
        )

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

    def _emit_code_for_rule_change(self, skip_if):
        # udev is supposed to have been picking up changed rules "for
        # years" (relative to 2016), so manually triggering a reload
        # does not appear to be called for any more.
        #
        # SUDO_SCRIPT.add_cmd(
        #     "udevadm control --reload",
        #     skip_if=skip_if,
        #     comment="Make udev take notice of the updated set of udev rules",
        # )

        # FIXME: In case installtool is running as root, run udevadm directly?

        udevadm_trigger_commands = [
            "udevadm control --reload  # ensure udev notes ruleset changes before the triggers",
        ] + [
            f"udevadm trigger --verbose --action=add --subsystem-match=usb --attr-match=idVendor={const.VENDOR_ID_HARMAN:04x} --attr-match=idProduct={pid:04x}"
            for pid in const.PY_LIST_OF_PRODUCT_IDS
        ]

        SUDO_SCRIPT.add_cmd(
            "\n".join(udevadm_trigger_commands),
            skip_if=skip_if,
            comment="Trigger the udev rules (just as when plugging in a Notepad mixer)",
        )

    def post_pip_install(self):
        # Populate with the files installed pre installation
        old_content = {}
        if self.udev_rules_dst.exists():
            old_content[self.udev_rules_dst] = self.udev_rules_dst.read_text()

        # Populate with the files which we (should/will) have installed
        new_content = {}
        new_content[self.udev_rules_dst] = self.udev_rules_content

        if common.VERBOSE:
            from pprint import pprint

            print("OLD")
            pprint(old_content)
            print("NEW")
            pprint(new_content)

        if old_content != new_content:
            super(UdevRulesInstallTool, self).post_pip_install()

        self._emit_code_for_rule_change(skip_if=(new_content == old_content))

    def pre_pip_uninstall(self):
        # FIXME05: Do we even want to uninstall the udev rules if it
        #          is in /etc/udev/rules.d for a $HOME/.local install?
        #          The next install will just need sudo access again
        #          to install it again.

        old_content = {}
        if self.udev_rules_dst.exists():
            old_content[self.udev_rules_dst] = self.udev_rules_dst.read_text()

        super(UdevRulesInstallTool, self).pre_pip_uninstall()

        new_content = dict(old_content)
        if self.udev_rules_dst in new_content:
            del new_content[self.udev_rules_dst]

        if common.VERBOSE:
            from pprint import pprint

            print("OLD")
            pprint(old_content)
            print("NEW")
            pprint(new_content)

        self._emit_code_for_rule_change(skip_if=(new_content == old_content))

    def package_build_install(self):
        super().package_build_install()
        self._emit_code_for_rule_change(skip_if=False)


class SudoScriptInstallTool(AbstractInstallTool):
    """Subsystem dealing with the sudo script"""

    def __init__(self, dry_run, sudo_script=None):
        super(SudoScriptInstallTool, self).__init__(
            dry_run=dry_run,
            heading=None,
        )
        self.__sudo_script = sudo_script

    def post_pip_install(self):
        SUDO_SCRIPT.finalize(sudo_script=self.__sudo_script, dry_run=self.dry_run)

    def pre_pip_uninstall(self):
        SUDO_SCRIPT.finalize(sudo_script=self.__sudo_script, dry_run=self.dry_run)

    def package_build_install(self):
        SUDO_SCRIPT.finalize(sudo_script=None, dry_run=self.dry_run)


class InstallToolEverything(AbstractInstallTool):
    """Groups all subsystem InstallTool objects into one"""

    def __init__(self):
        super(InstallToolEverything, self).__init__(dry_run=False, heading=None)
        self.everything = []

    def add(self, thing):
        self.everything.append(thing)

    def post_pip_install(self):
        print("Socranop Installation")
        print("=====================")
        print()
        for thing in self.everything:
            thing.post_pip_install()
        print()
        print(f"Socranop installation and setup completed.")
        print()
        print(
            f"You can now run `{const.BASE_EXE_GUI}` or `{const.BASE_EXE_CLI}` as a regular user."
        )

    def pre_pip_uninstall(self):
        print("Socranop Uninstallation Preparation")
        print("===================================")
        print()
        for thing in self.everything:
            thing.pre_pip_uninstall()
        print()
        print(f"Socranop uninstallation preparation completed.")
        print()
        print(
            f"To complete uninstalling, run `pip uninstall {const.PACKAGE}` and (if needed) the sudo commands."
        )

    def package_build_install(self):
        print("Socranop Package Build Installation")  # TODO: Improve wording
        print("===================================")
        print()
        for thing in self.everything:
            thing.package_build_install()
        print()
        print(f"Package build installation completed.")


def command_post_pip_install(everything, args):
    everything.post_pip_install()


def command_pre_pip_uninstall(everything, args):
    everything.pre_pip_uninstall()


def command_package_build_install(everything, args):
    everything.package_build_install()
    global files_to_delete
    files_to_delete.remove_all()


def parse_argv(argv=None):
    """Parse the command line arguments for socranop-installtool."""

    # Caution: If you change the command line parser in any way,
    #          update the man pages and bash completions accordingly.

    parser = argparse.ArgumentParser(
        description=f"Hook {const.PACKAGE} into the system post-install (or do the reverse).",
    )
    common.parser_args(parser)

    parser.add_argument(
        "-n",
        "--dry-run",
        help="Do not actually do anything, just show what would be done.",
        dest="dry_run",
        action="store_true",
    )

    subparsers = parser.add_subparsers(
        title="Commands",
        description="What kind of installation related action to perform.",
        metavar="COMMAND",
        dest="command",
        required=True,
    )

    parser_ppi = subparsers.add_parser(
        "post-pip-install",
        help=f"install and setup after 'pip install {const.PACKAGE}'",
    )

    parser_ppi.add_argument(
        "--no-launch",
        help="when installing, do not test launching the service",
        action="store_true",
    )

    parser_ppu = subparsers.add_parser(
        "pre-pip-uninstall",
        help=f"uninstall and undo setup before a 'pip uninstall {const.PACKAGE}'",
    )

    parser_pbi = subparsers.add_parser(
        "package-build-install",
        help=f"while building a {const.PACKAGE} package, run in the install step",
    )

    def add_sudo_script_argument(parser):
        parser.add_argument(
            "--sudo-script",
            metavar="FILENAME",
            help="write the script of sudo commands to the given FILENAME",
            default=None,
        )

    add_sudo_script_argument(parser_ppi)
    add_sudo_script_argument(parser_ppu)

    mutex_pbi = parser_pbi.add_mutually_exclusive_group(required=True)
    mutex_pbi.add_argument(
        "--chroot",
        metavar="CHROOT",
        help="package build root chroot directory",
        type=Path,
        default=None,
    )
    mutex_pbi.add_argument(
        "--force-prefix",
        help="force acceptance of non-standard installation prefix",
        action="store_true",
    )

    args = parser.parse_args(argv)
    print("args after parse_args:", args)

    if hasattr(args, "chroot") and hasattr(args, "force_prefix"):
        # Initialize the dirs object with the chroot given so that later
        # calls to get_dirs() will yield an object which uses the same
        # chroot value.
        dirs = init_dirs(chroot=args.chroot, force_prefix=args.force_prefix)
    elif (not hasattr(args, "chroot")) and (not hasattr(args, "force_prefix")):
        dirs = init_dirs()
    else:
        parser.error("Internal error related to chroot and force_prefix")
    common.debug("Using dirs", dirs)

    print("args", args)

    # args.dry_run = True

    common.VERBOSE = args.verbose

    if args.command == "post-pip-install":
        pass
    elif args.command == "pre-pip-uninstall":
        # Always false for pre-pip-uninstall, so there is no --no-launch argument
        setattr(args, "no_launch", False)
    elif args.command == "package-build-install":
        if args.chroot == "/":
            parser.error("The --chroot argument must not be /")
        print("Using chroot", args.chroot)

        # When building a package, we are working inside the package
        # chroot and starting/stopping the service does not make
        # sense.
        setattr(args, "no_launch", True)
        setattr(args, "sudo_script", None)
    else:
        parser.error(f"Unhandled command: {args.command}")

    print("args before return:", args)
    return args


def main(argv=None):
    """Main program for socranop-installtool."""

    args = parse_argv(argv)

    global files_to_delete
    files_to_delete = FilesToDelete()

    # In some cases, we can delete the socranop-installtool executable after use
    files_to_delete.add(Path(sys.argv[0]))

    # Module source file (socranop/installtool.py)
    files_to_delete.add(Path(__file__))

    # Compiled module source file (socranop/__pycache__/installtool.*.pyc)
    if "__cached__" in globals():
        pyc = Path(globals()["__cached__"])
        # Occasionally, there are two `*.pyc` files but `__cached__`
        # only points to one. So we use `__cached__` to find the
        # directory, and just remove all `installtool.*.pyc` files.
        for p in pyc.parent.glob("installtool.*.pyc"):
            files_to_delete.add(p)

    everything = InstallToolEverything()
    everything.add(CheckDependencies(dry_run=args.dry_run))
    everything.add(BashCompletionInstallTool(dry_run=args.dry_run))
    everything.add(DBusInstallTool(dry_run=args.dry_run, no_launch=args.no_launch))
    everything.add(ManpageInstallTool(dry_run=args.dry_run))
    everything.add(XDGDesktopInstallTool(dry_run=args.dry_run))
    everything.add(UdevRulesInstallTool(dry_run=args.dry_run))
    everything.add(
        SudoScriptInstallTool(dry_run=args.dry_run, sudo_script=args.sudo_script)
    )

    cmd_map = {
        "post-pip-install": command_post_pip_install,
        "pre-pip-uninstall": command_pre_pip_uninstall,
        "package-build-install": command_package_build_install,
    }

    cmd_map[args.command](everything, args)
