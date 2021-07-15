Distribution Packaging Guide
============================

This is just a placeholder for now, but here are some quick guidelines and suggestions:

- Distro packaging should call `socranop-installtool` to set up the
  non-pip-able bits as part of the "build" of the package.  Check
  `socranop-installtool --help` for some ideas, including the `--chroot`
  option.
- Distro packaging should ship reasonable udev rules as part of the package.
  See [PERMISSIONS.md](PERMISSIONS.md) for more details.
- There should be no need to ship the `socranop-installtool` executable in a
  distro package
