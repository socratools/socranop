NAME
====

socranop\-permissions \- setting up USB device permissions for use with socranop

DESCRIPTION
===========

The `socranop-session-service` D-Bus service and the `socranop-ctl
--no-dbus` CLI skipping the D-Bus service change the mixer audio routing
by opening and writing to the device special file corresponding to the
mixer.

By default, the device special file cannot be written by unpriviledged
users and since the `socranop-session-service` D-Bus service and the
`socranop-ctl --no-dbus` CLI run as an unpriviledged user, the device
special files's permission must be opened up to allow write access to
`socranop-session-service`.

A new device special file is created every time the mixer device is
connected to the host, so changing the device file's permissions by
running commands like **chown**(1), **chgrp**(1), **chmod**(1),
**setfacl**(1) will only be temporary.

The operating system has a set of rules which change device file
permissions whenever a device file is created.  There are many ways to
do this, but the following are some of the most commonly-used
mechanisms.


Linux/udev
==========

On Linux, the device special file is called something like something
like `/dev/bus/usb/006/014`, and the the device permissions are set by
**udev**(7) which can be configured by dropping rule files into a
special location in the filesystem.

The rule files are typically named something like
`/etc/udev/rules.d/70-socranop.rules`.

Every rule consists of a part to match a particular type of device
(with comparison operators such as `==`), and a part which does
something about that device, such as modifying or setting a variable
(e.g. `+=` or `=`), changing its file mode or ownership or file ACL.


Allow all local users
---------------------

Setting `TAG+="uaccess"` allows access to users with a local login
session.

```
# Soundcraft Notepad-5, Notepad-8FX and Notepad-12FX analog mixers with USB control
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0030", TAG+="uaccess"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0031", TAG+="uaccess"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0032", TAG+="uaccess"
```

Allow access for all members of the audio group
-----------------------------------------------

Setting the device file's group to *audio* allows all users in the
*audio* group access.

This is useful if you are for example remotely logging in via ssh and
want to run **socranop-ctl**(1). You could also choose to create a new
group for this purpose instead of reusing the operating system's
default *audio* group.

```
# Soundcraft Notepad-5, Notepad-8FX and Notepad-12FX analog mixers with USB control
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0030", GROUP="audio"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0031", GROUP="audio"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0032", GROUP="audio"
```


FILES
=====

Linux/udev
----------

/dev/bus/usb/NNN/MMM

: The USB device file

/etc/udev/rules.d/

: This is where the local system's administrator write their udev rule files.

/usr/lib/udev/rules.d/

: This is where operating system packages typically install their udev rule files.

/usr/local/lib/udev/rules.d/

: This is where installations to /usr/local packages typically install their udev rule files.


BUGS
====

For reading about known bugs and for filing new bugs, please go visit
[https://github.com/socratools/socranop/issues](https://github.com/socratools/socranop/issues).


SEE ALSO
========

**socranop-ctl(1)**, **socranop-gui(1)**, **socranop-session-service(1)**, [https://github.com/socratools/socranop](https://github.com/socratools/socranop)
