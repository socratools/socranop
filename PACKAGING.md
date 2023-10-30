Distribution Packaging Guide
============================

A `socranop` installation consists basically of four parts:

  * A Python library with the code and a few scripts using that code

  * Configuration files configuring e.g bash completions, D-Bus and
    the XDG Desktop menu

  * A udev rules file to allow unpriviledged users access to the USB
    device

  * Documentation files

The following describes the basic principles of the steps which build
my Fedora package, but they should be similar when building a package
for another Linux distribution.

  * Take the source code from the pypi source tarball. Unlike the
    binary wheel, the source tarball will include all files, such as
    documentation files.

  * Build, and install to `/usr` in a chroot `${chroot}`:

        python3 setup.py build
        python3 setup.py install --chroot ${chroot}

    These are the standard build and install commands for Python
    packages. There is nothing special here.

    Note: There might be an alternative way of first building a wheel,
          and then installing that wheel to the chroot.

  * Run `socranop-installtool` to install files into `${chroot}`:

        env PYTHONPATH=${chroot}/usr/lib/python3.8/site-packages \
        ${chroot}/usr/bin/socranop-installtool --post-install --chroot=${chroot}

    This installs the Bash completion files, the D-Bus service file,
    the XDG desktop menu and icon files, and udev rules file.

    The default udev rules file action is to `TAG+="uaccess"` which on
    modern Linux distributions will ensure access for locally logged
    in users. If you need to set up device permissions in another way,
    you can change `${chroot}/usr/lib/udev/rules.d/70-socranop.rules`
    accordingly or add additional udev rule files.

    See [PERMISSIONS.md](PERMISSIONS.md) for more details.

  * [optional] Remove the `${chroot}/usr/bin/socranop-installtool`
    script file and from the `.../site-packages` directory remove the
    `socranop/installtool.py` file and the `socranop/data` directory
    tree (FIXME: Remove the complete data/ tree? Really?)

    Those files will not be needed in the distro package, as those
    files were only needed to install files into the `${chroot}` which
    we have just done in the previous step.

    The uninstallation will be taken over by the package manager, so
    there is no need for running `socranop-installtool
    --pre-uninstall` at any time later either.

  * [optional] Move `${chroot}/usr/bin/socranop-session-service` to
    `${chroot}/usr/libexec/socranop-session-service` and change the
    `Exec` line inside the
    `${chroot}/usr/share/dbus-1/services/io.github.socratools.socranop.service`
    file accordingly (preferably in an automated way, e.g. using
    `sed`).

	Not all distributions mandate the use of `/usr/libexec` for
    service executables, and this is not necessary for a
    `socranop` distro package to work, but it does work if
    your distribution requires it.

  * Install documentation files into `${chroot}`.

When you notice something wrong or missing in this file, please [file
an issue](https://github.com/socratools/socranop/issues/new) or [file
a pull request](https://github.com/socratools/socranop/compare).
