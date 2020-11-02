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

import array
import enum
import json
import shutil

from pathlib import Path

import usb.core

import soundcraft.constants as const

from soundcraft.dirs import get_dirs


class NotepadBase:
    def __init__(
        self, idProduct, routingTarget, stateDir=None, fixedRouting=None,
    ):
        if fixedRouting is None:
            fixedRouting = []
        self.routingTarget = routingTarget
        self.fixedRouting = fixedRouting
        if not stateDir:
            stateDir = get_dirs().statedir
        else:
            # Note that the testsuite absolutely requires we convert
            # whatever type stateDir is to a Path.
            stateDir = Path(stateDir)
        print("Using stateDir", repr(stateDir))
        self.dev = usb.core.find(idVendor=const.VENDOR_ID_HARMAN, idProduct=idProduct)
        print("Found device", self.dev)
        if self.dev is not None:
            major = self.dev.bcdDevice >> 8
            minor = self.dev.bcdDevice & 0xFF
            try:
                self.product = self.dev.product
            except Exception:
                # Fall-back to class name, since reading the product over USB requires write access
                self.product = self.__class__.__name__
            self.fwVersion = "%d.%02d" % (major, minor)
            self.stateFile = stateDir / f"{self.product}.state"
            if self.stateFile.exists():
                print(self, "using existing stateFile", self.stateFile)
            else:
                # If self.stateFile does not exist, import the state
                # file from the old /var/lib location if one exists.
                # TODO: This should be removed some time in the future (seen from 2020-11).
                oldStateFile = Path(const.OLD_STATEDIR) / f"{self.product}.state"
                if oldStateFile.exists():
                    print(
                        self,
                        "using stateFile",
                        self.stateFile,
                        "copied over from old",
                        oldStateFile,
                    )
                    shutil.copy(oldStateFile, self.stateFile)
                else:
                    print(self, "using new stateFile", self.stateFile)
            self.state = {}
            self._loadState()

    def found(self):
        return self.dev is not None

    def resetState(self):
        storedSource = self.routingSource
        if storedSource == "UNKNOWN":
            return
        self.routingSource = storedSource

    @property
    def routingSource(self):
        if "source" not in self.state:
            return "UNKNOWN"
        return self.Sources(self.state["source"]).name

    @routingSource.setter
    def routingSource(self, request):
        assert self.found()
        source = self._parseSourcename(request)
        if source is None:
            raise ValueError(f"Requested input {request} is not a valid choice")
        print(f"Switching USB audio input to {source.name}")
        # Reverse engineered via Wireshark on Windows
        # 0 => 0x00 00 04 00 00 00 00 00
        # 1 => 0x00 00 04 00 01 00 00 00
        #        Change this -^
        message = array.array("B", [0x00, 0x00, 0x04, 0x00, source, 0x00, 0x00, 0x00])
        print(f"Sending {message}")
        self.dev.ctrl_transfer(0x40, 16, 0, 0, message)
        self.state["source"] = source
        self._saveState()

    @property
    def sources(self):
        return {x.name: self.Label[x] for x in self.Sources}

    @property
    def name(self):
        return f"{self.product} (fw v{self.fwVersion})"

    def fetchInfo(self):
        assert self.found()
        # TODO: Decode these?
        # Unfortunately, inspection shows none of the data here
        # corresponds to thr current source selection
        self.info1 = self.dev.ctrl_transfer(0xA1, 1, 0x0100, 0x2900, 256)
        self.info2 = self.dev.ctrl_transfer(0xA1, 2, 0x0100, 0x2900, 256)

    def _parseSourcename(self, request):
        sources = self.Sources
        if isinstance(request, self.Sources):
            return request
        if isinstance(request, int):
            return sources(request)
        try:
            num = int(request)
            return self._parseSourcename(num)
        except ValueError:
            try:
                return sources[request]
            except KeyError:
                for source in sources:
                    # This could be better; maybe ensure it's a unique substring?
                    if str(request) in source.name:
                        return source
        except Exception:
            pass
        return None

    def _saveState(self):
        try:
            print("self.stateFile", repr(self.stateFile))
            self.stateFile.parent.mkdir(mode=0o0755, parents=True, exist_ok=True)
            self.stateFile.write_text(json.dumps(self.state, sort_keys=True, indent=4))
        except Exception as e:
            print(f"Warning: Could not write state file: {e}")

    def _loadState(self):
        try:
            self.state = json.loads(self.stateFile.read_text())
        except Exception:
            pass  # keep current self.state if error reading state from file


def stereo_label(base):
    return (f"{base} L", f"{base} R")


class Notepad_12fx(NotepadBase):
    def __init__(self, **kwargs):
        super().__init__(
            idProduct=const.PRODUCT_ID_NOTEPAD_12FX,
            routingTarget=("capture_3", "capture_4"),
            fixedRouting=[(("capture_1", "capture_2"), ("Mic/Line 1", "Mic/Line 2"))],
            **kwargs,
        )

    class Sources(enum.IntEnum):
        INPUT_3_4 = 0
        INPUT_5_6 = 1
        INPUT_7_8 = 2
        MASTER_L_R = 3

    Label = {
        Sources.INPUT_3_4: ("Mic/Line 3", "Mic/Line 4"),
        Sources.INPUT_5_6: stereo_label("Stereo 5/6"),
        Sources.INPUT_7_8: stereo_label("Stereo 7/8"),
        Sources.MASTER_L_R: stereo_label("Mix"),
    }


class Notepad_8fx(NotepadBase):
    def __init__(self, **kwargs):
        super().__init__(
            idProduct=const.PRODUCT_ID_NOTEPAD_8FX,
            routingTarget=("capture_1", "capture_2"),
            **kwargs,
        )

    class Sources(enum.IntEnum):
        INPUT_1_2 = 0
        INPUT_3_4 = 1
        INPUT_5_6 = 2
        MASTER_L_R = 3

    Label = {
        Sources.INPUT_1_2: ("Mic/Line 1", "Mic/Line 2"),
        Sources.INPUT_3_4: stereo_label("Stereo 3/4"),
        Sources.INPUT_5_6: stereo_label("Stereo 5/6"),
        Sources.MASTER_L_R: stereo_label("Mix"),
    }


class Notepad_5(NotepadBase):
    def __init__(self, **kwargs):
        super().__init__(
            idProduct=const.PRODUCT_ID_NOTEPAD_5,
            routingTarget=("capture_1", "capture_2"),
            **kwargs,
        )

    class Sources(enum.IntEnum):
        MONO_1_MONO_2 = 0
        STEREO_2_3 = 1
        STEREO_4_5 = 2
        MASTER_L_R = 3

    Label = {
        Sources.MONO_1_MONO_2: ("Mic/Line 1", "Mono Line 2"),
        Sources.STEREO_2_3: stereo_label("Stereo 2/3"),
        Sources.STEREO_4_5: stereo_label("Stereo 4/5"),
        Sources.MASTER_L_R: stereo_label("Mix"),
    }


# Note: The stateDir parameter is required by the test suite.
def autodetect(stateDir=None):
    for devClass in (Notepad_12fx, Notepad_8fx, Notepad_5):
        dev = devClass(stateDir=stateDir)
        if dev.found():
            return dev
