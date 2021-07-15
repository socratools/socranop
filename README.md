Linux Utilities for Soundcraft Notepad Mixers
=============================================

[Soundcraft Notepad](https://www.soundcraft.com/en/product_families/notepad-series)
mixers are pretty nice small-sized mixer boards with Harmon USB I/O built-in.
While the USB audio works great in alsa/jackd/pipewire without any additional
configuration needed, there are some advanced features available to the Windows
driver that have no Linux equivalent.  Most importantly, the USB routing for
the capture channels is software-controlled, and requires an additional
utility.  For example, by default the Notepad-12FX sends the Master L&R outputs
to USB capture channels 3 and 4, but this routing can be changed to input 3&4,
input 5&6, or input 7&8.  This tool aims to give this same software control of
the USB capture channel routing to Linux users.

Supported models:
- Notepad-12FX
- Notepad-8FX
- Notepad-5


About the Name
--------------

**SO**und**CRA**ft **NO**te**P**ad

This software was originally written and published as
[soundcraft-utils](https://soundcraft-utils.github.io), but was renamed and
updated in 2021.  Version 0.4 of soundcraft-utils is considered end-of-life,
and will be expunged from the internet after an appropriate mourning period has
expired.

This renamed and updated version is still maintained by the original authors,
under the [socratools](https://github.com/socratools) organization.

### Legacy Upgrades

If you're upgrading from soundcraft-utils, this version is different enough
that it's worth uninstalling the soundcraft-utils and doing a fresh install of
socranop as outlined below.


Installation
------------

Note: This covers manual installation of the pypi package via pip.  For distro-specific packages see [the section below](#distro-specific-packages)

### Prerequisites

The D-Bus service and GTK GUI both rely on
[PyGObject](https://pygobject.readthedocs.io/en/latest/index.html) which is not
available via pypi without a lot of dev libraries for it to compile against.
It is usually easier to install separately using your distribution's package
installation tools:

Ubuntu:
```bash
sudo apt install python3-gi
```

Fedora:
```bash
sudo dnf install python3-gobject
```

### Installation

```bash
pip install socranop
```

It is fine to run this command as your non-root user to install just for the
local user, or as root to install system-wide.

Next, set up the D-Bus service, XDG desktop entry, man pages, and other things
pip can't do on its own:

```bash
socranop-installtool --post-install --sudo-script ./socranop-sudo.sh
# Inspect ./socranop-sudo.sh to make sure it's safe to run as root
sudo ./socranop-sudo.sh
rm ./socranop-sudo.sh
```

Again, this can be run as non-root to setup just for the current user, or as
root to setup system-wide.  How you run this should match the user you used to
run `pip`.

Regardless of whether this is run as root or as a non-root user, one additional
action must be taken to set up the udev rules, which can only be done as root.
The installtool example shown above will write the appropriate script into the
file specified, allowing for inspection before running as root.

Alternatively, you can ask `socranop-installtool` to write the script contents
to stdout instead of a file, by omitting the `--sudo-script` option.

See [PERMISSIONS.md](PERMISSIONS.md) for a more in-depth discussion about the
udev permission requirements, and alternative ways of granting the required
privileges.

### Upgrading

Simply update your package from pip, and rerun the 'setup' to ensure
the D-Bus service is upgraded to the latest version:

```bash
pip install -U socranop
socranop-installtool --post-install
```

It is not normally required to update the udev rules after an upgrade.

### Uninstallation

You can remove the D-Bus, XDG desktop entry, man pages, and other things
installed by `--post-install`, then remove the pip package by running:

```bash
socranop-installtool --pre-uninstall --sudo-script ./socranop-sudo.sh
# Inspect ./socranop-sudo.sh to make sure it's safe to run as root
sudo ./socranop-sudo.sh
rm ./socranop-sudo.sh
```

Finally, remove the socranop package:

```bash
pip uninstall socranop
```

### Distro-specific Packages

The previous version of this software, called `soundcraft-utils` had Arch Linux
and NixOS packages.  These will have to be re-done with the rename to
`socranop`.

Distro-specific packages will not require running `socranop-installtool` and
should instead install everything system-wide with appropriate udev
permissions.  See [PACKAGING.md](PACKAGING.md) for details.


Usage
-----

### GUI

The XDG desktop launcher should be installed by default, and most XDG-aware
application launchers should allow launching via a beautiful technicolor icon
alongside all your other favorite GUI applications.

The GUI can also be started manually via:

```bash
socranop-gui
```

#### Usage Tips

- Select the desired input using the up and down arrow keys or using the mouse
- Apply the selection by clicking "Apply" (ALT+A)
- Instead of applying the selection, clicking "Reset" (ALT+R) will set the
  selection back to the current state of the mixer (if known)

#### Screenshots

![GUI Window](images/gui-screenshot.png)
![GUI Window with drop-down open](images/gui-screenshot-with-dropdown.png)

### CLI

List possible channel routing choices:

```bash
socranop-ctl --list/-l
```

Set channel routing:

```bash
socranop-ctl --set/-s <number>
```

#### Sample Output

```
[user@host ~]$ socranop-ctl --list
Detected a Notepad-12FX (fw v1.09)
-----------------------------
capture_1 <- Mic/Line 1
capture_2 <- Mic/Line 2
-----------------------------
             Mic/Line 3   [0]
             Mic/Line 4
             Stereo 5/6 L [1]
             Stereo 5/6 R
capture_3 <- Stereo 7/8 L [2]
capture_4 <- Stereo 7/8 R
             Mix L        [3]
             Mix R
-----------------------------
[user@host ~]$ _
[user@host ~]$ socranop-ctl --set 3
Detected a Notepad-12FX (fw v1.09)
-----------------------------
capture_1 <- Mic/Line 1
capture_2 <- Mic/Line 2
-----------------------------
             Mic/Line 3   [0]
             Mic/Line 4
             Stereo 5/6 L [1]
             Stereo 5/6 R
             Stereo 7/8 L [2]
             Stereo 7/8 R
capture_3 <- Mix L        [3]
capture_4 <- Mix R
-----------------------------
[user@host ~]$ _
```

### D-Bus Service

The D-Bus service runs on the user's session bus unprivileged, and relies on
the proper udev device permissions to access the USB device to make changes. 
See [PERMISSIONS.md](PERMISSIONS.md) for a more in-depth discussion about the
udev permission requirements, and alternative ways of granting the required
privileges.

You can access the D-Bus service directly if you like; see
[contrib/dbus/access-dbus-service.sh](contrib/dbus/access-dbus-service.sh) for
an example using busctl, but any D-Bus client can do it.

Because both the GUI and CLI perform their operations via the D-Bus service,
any changes made through any client are immediately visible to all other
clients.

What's Next
-----------

To submit ideas or bugs, and see what we're working on next, see the [socranop
issues page](https://github.com/socratools/socranop/issues)
