#!/bin/sh
# ShaderBench - what each shader pipeline costs on this device.
#
# NOTHING IS DRAWN. The benchmark renders into an offscreen framebuffer and
# never presents, so the screen stays black for the whole run - a couple of
# minutes - and then the launcher comes back. That is what success looks like.
#
# Two files land next to this script, and log.txt holds everything, so there is
# only ever one file worth copying off the card:
#
#   log.txt      the self-test, the table, and any error
#   results.tsv  the table alone, for tools/report.py
#
# The self-test runs first and the measurement is skipped if it fails. The
# instrument has a way of being wrong that looks exactly like a fast shader -
# see docs/device-perf.md - so a failed self-test means the table is fiction.

cd "$(dirname "$0")" || exit 1

# Set here rather than inherited, so the same script works when it is launched
# over ssh, where none of the frontend's environment exists. Launched from the
# Tools menu this is already set and repeating it costs nothing.
SYSTEM_LIB=/mnt/SDCARD/.system/tg5040/lib
LD_LIBRARY_PATH="$SYSTEM_LIB:/usr/trimui/lib:$LD_LIBRARY_PATH"
export LD_LIBRARY_PATH

LOG=./log.txt
RESULTS=./results.tsv

# A stale table from an earlier run is worse than no table: it reads as a
# result, and nothing about it says which run produced it.
rm -f "$RESULTS"

{
    echo "# $(date)"
    echo "# $(uname -a)"
    echo

    if ./bench.elf --root "$(pwd)" --self-test; then
        echo
        ./bench.elf --root "$(pwd)" --out "$RESULTS"
        echo
        echo "done - results.tsv written"
    else
        echo
        echo "self-test failed, so nothing was measured and no results.tsv was"
        echo "written. The checks above say which one failed."
    fi
} 2>&1 | tee "$LOG"
