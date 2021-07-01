# socranop/installtool.py - post-install and pre-uninstall commands
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

from socranop.dirs import get_dirs, init_dirs


class ScriptCommand:
    """A single command which may need to be run in a sudo script

    These commands are to be collected into a shell script.  We do
    *not* run these commands directly via `subprocess.*`.

    Therefore, storing the command as a string containing a shell
    command is a good fit.
    """

    def __init__(self, cmd, skip_if=False, comment=None):
        # print("ScriptCommand.__init__", repr(cmd))
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
            print(f"    [skip] {c.cmd!r}")
        else:
            c = ScriptCommand(cmd, skip_if=False, comment=comment)
            print(f"    [q'ed] {c.cmd!r}")
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
        print(f"  [inst] {self.dst}")
        """Install this file (either directly from python or via sudo script)"""
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
        print(f"  [rm] {self.dst}")
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

    def post_install(self):
        # Note that re-raising the exception after printing our own
        # error message is useful: It gives the user the hint about
        # which packages need to be installed, but still shows the
        # backtrace in case of an exception occuring which we had not
        # foreseen might happen.

        # If installing to a chroot environment, we cannot check what
        # is installed in that chroot environment, and therefore skip
        # the checks.
        if get_dirs().chroot:
            print("Installing to chroot, skipping module import checks.")
            return

        try:
            import gi  # noqa: F401 'gi' imported but unused
        except ModuleNotFoundError:
            print(
                "The PyGI library must be installed from your distribution; usually called python-gi, python-gobject, python3-gobject, pygobject, or something similar."
            )
            raise

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
                try:
                    print(f"Trying to require module {module} version {version}")
                    gi.require_version(module, version)
                except ValueError:
                    print(
                        f"Error: module '{mod_name}' not available in version %{version}. Make sure the package providing the '{typelib}' file is installed with the required dependencies."
                    )
                    raise

            try:
                print(f"Trying to import {mod_name}")
                importlib.import_module(mod_name)  # import must work; discard retval
            except ImportError:
                print(
                    f"Error importing module '{mod_name}'. Make sure the package providing the '{typelib}' file is installed with its required dependencies."
                )
                raise

        # pydbus internally requires gi and GLib, Gio, GObject
        try:
            import pydbus  # noqa: F401 'pydbus' imported but unused
        except Exception:
            print(
                "Error importing module pydbus. Make sure the pydbus package is installed."
            )
            raise

        try:
            import usb.core  # noqa: F401 'usb.core' imported but unused
        except ModuleNotFoundError:
            print(
                f"Module 'usb.core' not found. Make sure the 'pyusb' package is installed."
            )
            raise
        try:
            # check that finding any USB device works
            usb_devices = usb.core.find(find_all=True)
            if len(list(usb_devices)) == 0:
                raise
                raise ValueError("No USB devices found")
        except ValueError:
            print("Error: No USB devices found. Something is broken here.")
            raise

        print("Checking installed packages: Good.")

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

    def __init__(self):
        super(FileInstallTool, self).__init__()
        self.files = []

    def add_file(self, file):
        print("Adding file", self, file)
        self.files.append(file)

    def post_install(self):
        for file in sorted(self.files, key=FileInstallTool.destfile_key):
            file._install()

    def pre_uninstall(self):
        for file in sorted(self.files, key=FileInstallTool.destfile_key, reverse=True):
            file._uninstall()


class ResourceInstallTool(FileInstallTool):
    """A subsystem which iterates through resources in data/"""

    def walk_resources(self, resdir):
        print("walk_through_data_files", self, resdir)
        assert resource_isdir(RESOURCE_MODULE, "data")

        def walk_resource_subdir(subdir):
            full_subdir = f"data/{subdir}"
            assert resource_isdir(RESOURCE_MODULE, full_subdir)
            for name in resource_listdir(RESOURCE_MODULE, full_subdir):
                full_name = f"{full_subdir}/{name}"
                print("res fullname", full_name)
                if resource_isdir(RESOURCE_MODULE, full_name):
                    walk_resource_subdir(f"{subdir}/{name}")
                else:
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
        super(DBusInstallTool, self).__init__()
        self.no_launch = no_launch

        print("DBusInstallTool walk_through_data_files")
        self.walk_resources("dbus-1")

    def add_resource(self, fullname):
        print("add_resource", self, fullname)
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
        if not self.no_launch:
            import pydbus

            bus = pydbus.SessionBus()
            dbus_service = bus.get(".DBus")

            if not dbus_service.NameHasOwner(const.BUSNAME):
                print("Old D-Bus service not running")
            else:
                service = bus.get(const.BUSNAME)
                service_version = service.version
                print(f"Shutting down old D-Bus service version {service_version}")
                service.Shutdown()
                print("Old session D-Bus service stopped")

        super(DBusInstallTool, self).post_install()

        if not self.no_launch:
            print(f"Starting D-Bus service {const.BUSNAME} as a test...")
            print(f"Installtool version: {const.VERSION}")

            # CheckDependencies.post_install() has already checked this import works
            import gi.repository.GLib

            # Give the D-Bus a few seconds to notice the new service file
            timeout = 5
            while True:
                try:
                    dbus_service.StartServiceByName(const.BUSNAME, 0)
                    break  # service has been started, no need to try again
                except gi.repository.GLib.Error:
                    # If the bus has not recognized the service config file
                    # yet, the service is not bus activatable yet and thus the
                    # GLibError will happen.
                    if timeout == 0:
                        raise

                    print(f"Retrying {timeout}...")
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
            import pydbus

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


class XDGDesktopInstallTool(ResourceInstallTool):
    """Subsystem dealing with the XDG desktop and icon files"""

    # FIXME05: Find out whether `xdg-desktop-menu` and `xdg-desktop-icon`
    #          must be run after all. Fedora Packaging docs suggest so.

    def __init__(self):
        super(XDGDesktopInstallTool, self).__init__()
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


class UdevRulesInstallTool(FileInstallTool):
    """Subsystem dealing with the udev rules"""

    # FIXME: udev is Linux-only. What about non-Linux systems?

    def __init__(self):
        super(UdevRulesInstallTool, self).__init__()

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
        # udev is supposed to be picking up changed rules "for years"
        # (relative to 2016), so manually triggering a reload does not
        # appear to be called for any more.
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

        from pprint import pprint

        print("OLD")
        pprint(old_content)
        print("NEW")
        pprint(new_content)

        self.emit_code_for_rule_change(skip_if=(new_content == old_content))


class ObsoleteThingsInstallTool(AbstractInstallTool):
    """Subsystem trying to clean up leftovers from old installs"""

    def post_install(self):
        self.check_install()

    def pre_uninstall(self):
        self.check_install()

    def check_install(self):
        dirs = get_dirs()
        if not dirs.chroot:
            self.stop_system_bus_service()
            self.remove_obsolete_files()

    def stop_system_bus_service(self):
        """Stop the obsolete system bus service"""
        print("Stopping obsolete D-Bus service on the system bus (when possible)")

        import pydbus

        old_busname = "socranop.utils"
        bus = pydbus.SystemBus()
        dbus_service = bus.get(".DBus")
        if not dbus_service.NameHasOwner(old_busname):
            print("Obsolete system D-Bus service is not running.")
        else:
            bus.get(old_busname).Shutdown()
            print("Stopped obsolete system D-Bus service.")

    def remove_obsolete_files(self):
        """Remove obsolete files from older installations"""
        print("Remove obsolete files from older installations")

        old_statedir = Path("/var/lib/socranop")
        if old_statedir.is_dir():
            SUDO_SCRIPT.add_cmd(
                f"rmdir {old_statedir}",
                comment="Remove obsolete state directory (if empty)",
            )

        # Old installs always installed into "/usr/share/dbus-1".
        old_dbus1dir = Path("/usr/share/dbus-1")
        obsolete_files = [
            old_dbus1dir / "system.d/socranop.conf",
            old_dbus1dir / "system-services/socranop.utils.notepad.service",
            Path("/usr/local/bin") / const.OLD_BASE_EXE_SERVICE,
            Path("/usr/bin") / const.OLD_BASE_EXE_SERVICE,
        ]
        files_to_delete = [str(f) for f in obsolete_files if f.exists()]
        delete_str = " ".join(files_to_delete)
        if files_to_delete:
            SUDO_SCRIPT.add_cmd(
                f"rm -f {delete_str}",
                comment="Remove obsolete system D-Bus service config and script files (from pre-0.5.0)",
            )


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

    parser.add_argument(
        "--sudo-script",
        metavar="FILENAME",
        help="write the script of sudo commands to the given FILENAME",
        default=None,
    )

    args = parser.parse_args()
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
    print("Using dirs", dirs)

    everything = InstallToolEverything()
    everything.add(CheckDependencies())
    everything.add(ObsoleteThingsInstallTool())
    everything.add(DBusInstallTool(no_launch=args.no_launch))
    everything.add(XDGDesktopInstallTool())
    everything.add(UdevRulesInstallTool())

    if args.post_install:
        everything.post_install()
    elif args.pre_uninstall:
        everything.pre_uninstall()

    if args.chroot:
        return

    if (args.sudo_script is None) or (args.sudo_script in ["", "-"]):
        sudo_script_file = io.StringIO()
    else:
        sudo_script_file = open(args.sudo_script, "w")
        p = Path(args.sudo_script)
        p.chmod(0o0755)

    if not SUDO_SCRIPT.needs_to_run():
        print("No commands left over to run with sudo. Good.")
        SUDO_SCRIPT.write(sudo_script_file)
        sys.exit(0)

    SUDO_SCRIPT.write(sudo_script_file)

    if isinstance(sudo_script_file, io.StringIO):
        print("You should probably run the following commands with sudo:")
        print()
        sys.stdout.write(sudo_script_file.getvalue())
        print()
    else:
        sudo_script_file.close()
        print("You should probably run this script with sudo (example command below):")
        print()
        sys.stdout.write(p.read_text())
        print()
        print("Suggested command:", "sudo", p.absolute())
