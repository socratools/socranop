Device permission setup using udev
==================================

The `socranop` D-Bus session changes the mixer audio routing opening and
writing to the device special file connected to the mixer, which is called
something like `/dev/bus/usb/006/004`.  By default, this cannot be written to
by ordinary users and since our D-Bus service runs as an ordinary user, we need
to open up the permissions a bit for it to function.

There are many ways to do this, but the following are the most commonly-used mechanisms:


Allow all local users
---------------------

Setting `TAG+="uaccess"`, which allows access to users with a local login session.

```
# Soundcraft Notepad 5, Notepad 8FX and Notepad 12FX analog mixers with USB control
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0030", TAG+="uaccess"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0031", TAG+="uaccess"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0032", TAG+="uaccess"
```


Restrict access to the audio group
----------------------------------

Setting the device file's group to `audio` to allow all users in the `audio` group access

```
# Soundcraft Notepad 5, Notepad 8FX and Notepad 12FX analog mixers with USB control
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0030", GROUP="audio"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0031", GROUP="audio"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="05fc", ATTRS{idProduct}=="0032", GROUP="audio"
```
