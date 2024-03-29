#
# Copyright (c) 2020,2021 Jim Ramsay <i.am@jimramsay.com>
# Copyright (c) 2021 Hans Ulrich Niedermann <hun@n-dimensional.de>
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

import argparse
import sys

import socranop.common as common


def autodetect(dbus=True, wait=False):
    if dbus:
        try:
            from socranop.dbus import Client, DbusInitializationError

            client = Client()
            result = client.autodetect()
            if result is None and wait:
                print("No devices found... waiting for one to appear")
                try:
                    result = client.waitForDevice()
                except KeyboardInterrupt:
                    pass
            return result
        except DbusInitializationError as e:
            print(e)
            sys.exit(2)
    else:
        import socranop.notepad

        result = socranop.notepad.autodetect()
        if result is None and wait:
            print(
                "Warning: '--wait' only works with D-Bus.  Exiting immediately instead."
            )
        return result


def max_lengths(dev):
    target_len = max([len(x) for x in dev.routingTarget])
    source_len = 0
    for source in dev.sources.values():
        source_len = max(source_len, *[len(x) for x in source])
    for target, source in dev.fixedRouting:
        target_len = max(target_len, *[len(x) for x in target])
        source_len = max(source_len, *[len(x) for x in source])
    return (target_len, source_len)


def show(dev):
    (target_len, source_len) = max_lengths(dev)
    table_width = target_len + 4 + source_len + 4
    print("-" * table_width)
    for target, source in dev.fixedRouting:
        for i in range(0, len(target)):
            print(f"{target[i]:<{target_len}} <- {source[i]}")
        print("-" * table_width)
    target = [x.ljust(target_len) for x in dev.routingTarget]
    notarget = (" " * target_len, " " * target_len)
    for i, source in enumerate(dev.sources.items()):
        sep = "  "
        input = [x.ljust(source_len) for x in source[1]]
        if dev.routingSource is None or dev.routingSource == "UNKNOWN":
            sep = "??"
            selected = target if i == 0 else notarget
        elif dev.routingSource == source[0]:
            selected = target
            sep = "<-"
        else:
            selected = notarget
        for j in range(0, len(selected)):
            idx = f"[{i}]" if j == 0 else ""
            print(f"{selected[j]} {sep} {input[j]} {idx}")
    print("-" * table_width)


def parse_argv(argv=None):
    """Parse the command line arguments for `socranop-ctl`."""

    # Caution: If you change the command line parser in any way,
    #          update the man pages and bash completions accordingly.

    parser = argparse.ArgumentParser(
        description="Control a Soundcraft Notepad series mixer from the command line."
    )
    common.parser_args(parser)

    parser.add_argument(
        "--no-dbus",
        help="Use direct USB device access instead of D-Bus service access",
        action="store_true",
    )
    parser.add_argument(
        "-w",
        "--wait",
        help="If no compatible device is found, wait for one to appear (D-Bus mode only)",
        action="store_true",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-l",
        "--list",
        help="List the available source routing options",
        action="store_true",
    )
    group.add_argument(
        "-s",
        "--set",
        help="Route specified source to USB capture input",
        choices=["0", "1", "2", "3"],
    )

    args = parser.parse_args(argv)
    common.VERBOSE = args.verbose
    return args


def main(argv=None):
    """Main program for `socranop-ctl`."""

    args = parse_argv(argv)

    dev = autodetect(dbus=not args.no_dbus, wait=args.wait)
    if dev is None:
        print("No compatible device detected")
        sys.exit(1)
    print(f"Detected a {dev.name}")
    if args.set:
        try:
            dev.routingSource = args.set
        except ValueError:
            print(f"Unrecognised input choice {args.set}")
            print("Run -l to list the valid choices")
            sys.exit(1)

    # Show the device state for both `args.list` and `args.set`
    show(dev)


if __name__ == "__main__":
    main()
