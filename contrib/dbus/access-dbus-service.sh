#!/bin/sh

# This script illustrates how to access the D-Bus interface from the
# shell, either from an interactive shell command line or from a shell
# script, using systemd's busctl tool.

busctl="busctl"

busname="soundcraft.utils.notepad"
devinterface="soundcraft.utils.notepad.device"
devpath="/soundcraft/utils/notepad/0"

set -xe

# Start the soundcraft-utils D-Bus service via bus activation on the
# system bus.

# dbus-send --system --print-reply --dest=org.freedesktop.DBus \
#	  /org/freedesktop/DBus org.freedesktop.DBus.StartServiceByName \
#	  "string:${busname}" uint32:0

# Note that busctl has beautiful bash shell completion for bus names
# etc.

${busctl} call org.freedesktop.DBus /org/freedesktop/DBus \
       org.freedesktop.DBus StartServiceByName su "${busname}" 0

sleep 2

# See what objects the soundcraft-utils D-Bus service exposes on the
# system bus.

${busctl} tree "${busname}"
${busctl} --no-pager introspect "${busname}" "$devpath"

${busctl} get-property "${busname}" "$devpath" "$devinterface" sources

${busctl} get-property "${busname}" "$devpath" "$devinterface" routingSource

${busctl} set-property "${busname}" "$devpath" "$devinterface" s MASTER_L_R
