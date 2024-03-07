# socranop/common.py - Define common functions for socranop
#
# Copyright (c) 2020,2021 Jim Ramsay <i.am@jimramsay.com>
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


"""\
Common utility functions
"""

import logging
import os

import socranop.constants as const


# TODO: Move all debug print()s over to .debug .info .warning .error


def add_parser_args(parser):
    # Caution: If you change the command line parser in any way,
    #          update the man pages and bash completions accordingly.

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s ({const.PACKAGE}) {const.VERSION}",
    )

    verbosity_mutex = parser.add_mutually_exclusive_group()
    verbosity_mutex.add_argument(
        "-L",
        "--log-level",
        help="set the log level: one of DEBUG, INFO, WARNING (default), ERROR, CRITICAL",
        metavar="LOGLEVEL",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
    )
    verbosity_mutex.add_argument(
        "-q",
        "--quiet",
        help="make program output less verbose",
        action="count",
        default=0,
    )
    verbosity_mutex.add_argument(
        "-v",
        "--verbose",
        help="make program output more verbose (mostly for debugging)",
        action="count",
        default=0,
    )


STRING_TO_LOGLEVEL = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


# https://docs.python.org/3.9/howto/logging.html#logging-basic-tutorial
def process_args(parser, args):
    print("##  process_args")
    if args.log_level:
        print("##  args.log_level")
        log_level = STRING_TO_LOGLEVEL[args.log_level]
    elif (args.verbose == 0) and (args.quiet == 0):
        # neither arg has been given, use default from env var or static default
        print("##  os.environ or default")
        ll_str = os.getenv(const.ENVVAR_LOGLEVEL, "WARNING")
        print("##  %r" % ll_str)
        log_level = STRING_TO_LOGLEVEL[ll_str]
    else:
        print("##  calculate loglevel")
        verbosity = args.verbose - args.quiet

        if verbosity < -2:
            parser.error("Too many ( -q | --quiet ) flags")
        elif verbosity > 2:
            parser.error("Too many ( -v | --verbose ) flags")

        log_level = {
            -2: logging.CRITICAL,
            -1: logging.ERROR,
            0: logging.WARNING,
            1: logging.INFO,
            2: logging.DEBUG,
        }[verbosity]

    print("##>> log_level", logging.getLevelName(log_level))
    logging.basicConfig(level=log_level, format="[%(levelname)s] %(message)s")


def process_gtk_options(options: dict):
    if (
        "log-level" not in options
        and "verbose" not in options
        and "quiet" not in options
    ):
        if const.ENVVAR_LOGLEVEL in os.environ:
            log_level = STRING_TO_LOGLEVEL[os.environ[const.ENVVAR_LOGLEVEL]]
        else:
            # default log level
            log_level = logging.WARNING
    elif "log-level" in options and "verbose" not in options and "quiet" not in options:
        log_level = STRING_TO_LOGLEVEL[options["log-level"]]
    elif "log-level" not in options and "verbose" in options and "quiet" not in options:
        # Gtk does not handle multiple --verbose options
        log_level = logging.DEBUG
    elif "log-level" not in options and "verbose" not in options and "quiet" in options:
        # Gtk does not handle multiple --quiet options
        log_level = logging.ERROR
    else:
        raise Exception(
            "Cannot handle more than one of the options --log-level --quiet --verbose"
        )

    logging.basicConfig(level=log_level, format="[%(levelname)s] %(message)s")
