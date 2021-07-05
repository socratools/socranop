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
#
########################################################################
#
# This file is intended to work without importing any non-standard
# Python libraries; ideally without any imports at all.
#
# This allows us to import this both from the setuptools `setup.py`
# and from any code inside `socranop/` as well.
#
########################################################################

# Package name
PACKAGE = "socranop"
VERSION = "0.4.92"

# Executable names
BASE_EXE_CLI = "socranop-ctl"
BASE_EXE_GUI = "socranop-gui"
BASE_EXE_SERVICE = "socranop-session-service"
BASE_EXE_INSTALLTOOL = "socranop-installtool"


# Gtk Application ID of the socranop GUI
# https://developer.gnome.org/gio/stable/GApplication.html#g-application-id-is-valid
APPLICATION_ID = "io.github.socratools.socranop"


# The complete set of D-Bus API strings
BUSNAME = "io.github.socratools.socranop"
DEVICE_INTERFACE = f"{BUSNAME}.device"
SERVICE_INTERFACE = BUSNAME
MGRPATH = "/io/github/socratools/socranop"


# USB Device vendor and product IDs
VENDOR_ID_HARMAN = 0x05FC

PRODUCT_ID_NOTEPAD_5 = 0x0030
PRODUCT_ID_NOTEPAD_8FX = 0x0031
PRODUCT_ID_NOTEPAD_12FX = 0x0032
PY_LIST_OF_PRODUCT_IDS = [
    PRODUCT_ID_NOTEPAD_5,
    PRODUCT_ID_NOTEPAD_8FX,
    PRODUCT_ID_NOTEPAD_12FX,
]
